import pytest

from conftest import FAKE_TASK_ID
from models import Status


def test_create_credit_returns_202_with_task_and_credit_ids(client, db, queued):
    response = client.post("/credits", json={"user_id": "u_123", "amount": 50})

    assert response.status_code == 202
    body = response.json()
    assert body["task_id"] == FAKE_TASK_ID
    assert body["status"] == Status.PROCESSING.value
    queued.assert_called_once_with(body["credit_id"])


def test_create_credit_stores_credit_and_marks_user_processing(client, db):
    credit_id = client.post("/credits", json={"user_id": "u_123", "amount": 50}).json()["credit_id"]

    credit = db.credits.find_one({"_id": credit_id})
    assert credit["user_id"] == "u_123"
    assert credit["amount"] == 50
    assert credit["status"] == Status.PROCESSING.value

    user = db.users.find_one({"user_id": "u_123"})
    assert user["status"] == Status.PROCESSING.value
    # The API never writes the balance; only the worker does.
    assert "balance" not in user


def test_create_credit_keeps_existing_balance(client, db):
    db.users.insert_one({"user_id": "u_123", "balance": 150.0, "status": "processed"})

    client.post("/credits", json={"user_id": "u_123", "amount": 50})

    assert db.users.find_one({"user_id": "u_123"})["balance"] == 150.0


@pytest.mark.parametrize(
    "payload",
    [
        {"user_id": "u_123", "amount": 0},
        {"user_id": "u_123", "amount": -450},
        {"user_id": "u_123", "amount": "fifty"},
        {"user_id": "u_123"},
        {"amount": 50},
        {"user_id": "", "amount": 50},
        {"user_id": "   ", "amount": 50},
    ],
    ids=[
        "zero",
        "negative",
        "not-a-number",
        "missing-amount",
        "missing-user",
        "empty-user",
        "whitespace-user",
    ],
)
def test_create_credit_rejects_invalid_requests(client, db, queued, payload):
    response = client.post("/credits", json=payload)

    assert response.status_code == 422
    assert db.credits.count_documents({}) == 0
    assert db.users.count_documents({}) == 0
    queued.assert_not_called()


def test_create_credit_strips_whitespace_from_user_id(client, db):
    client.post("/credits", json={"user_id": "  u_123  ", "amount": 50})
    client.post("/credits", json={"user_id": "u_123", "amount": 25})

    # Both requests belong to the same user, not two separate ones.
    assert db.users.count_documents({}) == 1
    assert db.users.find_one()["user_id"] == "u_123"
    assert {c["user_id"] for c in db.credits.find()} == {"u_123"}


def test_get_credit_returns_id_not_mongo_id(client):
    credit_id = client.post("/credits", json={"user_id": "u_123", "amount": 50}).json()["credit_id"]

    response = client.get(f"/credits/{credit_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == credit_id
    assert "_id" not in body


def test_get_unknown_credit_returns_404(client):
    assert client.get("/credits/does-not-exist").status_code == 404


def test_get_unknown_user_returns_404(client):
    assert client.get("/users/nobody").status_code == 404


def test_get_user_credits_returns_only_that_users_credits(client):
    first = client.post("/credits", json={"user_id": "u_123", "amount": 100}).json()
    second = client.post("/credits", json={"user_id": "u_123", "amount": 50}).json()
    client.post("/credits", json={"user_id": "u_456", "amount": 10})

    response = client.get("/users/u_123/credits")

    assert response.status_code == 200
    credits = response.json()
    assert {c["id"] for c in credits} == {first["credit_id"], second["credit_id"]}
    assert {c["amount"] for c in credits} == {100, 50}
    assert all(c["user_id"] == "u_123" for c in credits)
    assert all("_id" not in c for c in credits)


def test_get_credits_for_unknown_user_returns_404(client):
    assert client.get("/users/nobody/credits").status_code == 404


def test_get_credits_for_user_with_none_returns_empty_list(client, db):
    db.users.insert_one({"user_id": "u_123", "status": Status.PROCESSED.value})

    response = client.get("/users/u_123/credits")

    assert response.status_code == 200
    assert response.json() == []


def test_get_user_credits_newest_first(client, db):
    db.users.insert_one({"user_id": "u_123"})
    db.credits.insert_many(
        [
            {"_id": "old", "user_id": "u_123", "amount": 1, "created_at": 100.0},
            {"_id": "new", "user_id": "u_123", "amount": 2, "created_at": 300.0},
            {"_id": "mid", "user_id": "u_123", "amount": 3, "created_at": 200.0},
        ]
    )

    ids = [c["id"] for c in client.get("/users/u_123/credits").json()]

    assert ids == ["new", "mid", "old"]


def test_get_user_credits_returns_at_most_100(client, db):
    db.users.insert_one({"user_id": "u_123"})
    db.credits.insert_many(
        [
            {"_id": f"c{i}", "user_id": "u_123", "amount": 1, "created_at": float(i)}
            for i in range(101)
        ]
    )

    credits = client.get("/users/u_123/credits").json()

    assert len(credits) == 100
    assert credits[0]["id"] == "c100"


def test_metrics_counts_credits_by_status(client, db):
    db.credits.insert_many(
        [
            {"_id": "c1", "status": Status.PROCESSED.value},
            {"_id": "c2", "status": Status.PROCESSED.value},
            {"_id": "c3", "status": Status.PROCESSING.value},
        ]
    )
    db.users.insert_one({"user_id": "u_123"})

    assert client.get("/metrics").json() == {
        "total_credits": 3,
        "processing_credits": 1,
        "completed_credits": 2,
        "failed_credits": 0,
        "total_users": 1,
    }
