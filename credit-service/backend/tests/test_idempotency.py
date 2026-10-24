"""A credit must be applied to the balance exactly once, however many times its task runs.

Celery can deliver a task more than once (for example with acks_late after a
worker crash), so process_credit has to be safe to repeat.
"""
import pytest

import worker
from models import Status
from worker import process_credit
from test_worker import add_credit


class CrashOnCreditWrite:
    """Stands in for the worker's db and crashes on the first write to `credits`.

    This simulates a worker dying after it has updated the user but before it
    has marked the credit processed. Reads, and every write to other
    collections, go through to the real database.
    """

    WRITE_METHODS = {"update_one", "update_many", "find_one_and_update", "replace_one"}

    def __init__(self, real_db):
        self.real_db = real_db
        self.crashed = False

    def __getattr__(self, name):
        collection = getattr(self.real_db, name)
        if name != "credits":
            return collection
        return _CrashingCollection(collection, self)


class _CrashingCollection:
    def __init__(self, collection, owner):
        self.collection = collection
        self.owner = owner

    def __getattr__(self, name):
        method = getattr(self.collection, name)
        if name in CrashOnCreditWrite.WRITE_METHODS and not self.owner.crashed:
            def crash(*args, **kwargs):
                self.owner.crashed = True
                raise RuntimeError("simulated worker crash")
            return crash
        return method


def test_processing_the_same_credit_twice_only_credits_once(db):
    add_credit(db, "c1", "u_123", 50.0)

    process_credit("c1")
    process_credit("c1")

    user = db.users.find_one({"user_id": "u_123"})
    assert user["balance"] == 50.0
    assert user["status"] == Status.PROCESSED.value


def test_retry_after_crash_between_user_and_credit_updates(db, monkeypatch):
    add_credit(db, "c1", "u_123", 50.0)

    # First attempt: the user update lands, then the worker "dies".
    monkeypatch.setattr(worker, "db", CrashOnCreditWrite(db))
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        process_credit("c1")
    assert db.users.find_one({"user_id": "u_123"})["balance"] == 50.0
    assert db.credits.find_one({"_id": "c1"})["status"] == Status.PROCESSING.value

    # Celery redelivers the task to a healthy worker.
    monkeypatch.setattr(worker, "db", db)
    process_credit("c1")

    assert db.users.find_one({"user_id": "u_123"})["balance"] == 50.0
    assert db.credits.find_one({"_id": "c1"})["status"] == Status.PROCESSED.value


def test_repeats_dont_block_other_credits(db):
    add_credit(db, "c1", "u_123", 100.0)
    add_credit(db, "c2", "u_123", 50.0)

    process_credit("c1")
    process_credit("c1")
    process_credit("c2")
    process_credit("c2")

    assert db.users.find_one({"user_id": "u_123"})["balance"] == 150.0


def test_repeats_dont_create_extra_user_documents(db):
    add_credit(db, "c1", "u_123", 50.0)

    process_credit("c1")
    process_credit("c1")

    assert db.users.count_documents({"user_id": "u_123"}) == 1
