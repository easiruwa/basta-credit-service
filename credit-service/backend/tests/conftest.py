"""Shared test setup.

The tests run against a real MongoDB (start it with `docker compose up -d mongo`)
but use a separate database, so they never touch the app's data. Celery isn't
needed: API tests replace the task's `.delay()` with a mock, and worker tests
call the task function directly.
"""
import os
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pymongo import AsyncMongoClient, MongoClient
from pymongo.errors import ServerSelectionTimeoutError

import main
import worker

MONGO_URL = os.environ.get("TEST_MONGO_URL", "mongodb://localhost:27017")
TEST_DB = "credit_test"


@pytest.fixture(scope="session")
def mongo_client():
    client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=2000)
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError:
        message = f"MongoDB isn't reachable at {MONGO_URL}. Run `docker compose up -d mongo`."
        # CI sets REQUIRE_MONGO so a missing database fails the run instead of skipping it.
        if os.environ.get("REQUIRE_MONGO"):
            pytest.fail(message)
        pytest.skip(message)
    yield client
    client.close()


@pytest.fixture
def db(mongo_client, monkeypatch):
    """A clean test database, wired into both the worker and the API."""
    mongo_client.drop_database(TEST_DB)
    test_db = mongo_client[TEST_DB]

    monkeypatch.setattr(worker, "db", test_db)
    # The API uses the async client. It connects on first use, which happens
    # inside the TestClient's event loop.
    monkeypatch.setattr(main, "db", AsyncMongoClient(MONGO_URL)[TEST_DB])

    yield test_db
    mongo_client.drop_database(TEST_DB)


@pytest.fixture
def queued(monkeypatch):
    """Replaces process_credit.delay so no message is sent to Redis.

    Tests can check what would have been queued with `queued.assert_called_once_with(...)`.
    """
    mock = MagicMock()
    monkeypatch.setattr(main.process_credit, "delay", mock)
    return mock


@pytest.fixture
def client(db, queued):
    with TestClient(main.app) as c:
        yield c
