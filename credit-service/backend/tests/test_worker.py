import pytest

from models import Status
from worker import process_credit


def add_credit(db, credit_id, user_id, amount):
    """Sets up the state the API leaves behind before queuing a task."""
    db.credits.insert_one(
        {
            "_id": credit_id,
            "user_id": user_id,
            "amount": amount,
            "status": Status.PROCESSING.value,
        }
    )
    db.users.update_one(
        {"user_id": user_id},
        {"$set": {"status": Status.PROCESSING.value}},
        upsert=True,
    )


def test_first_credit_creates_the_balance_field(db):
    add_credit(db, "c1", "u_123", 150.0)

    process_credit("c1")

    user = db.users.find_one({"user_id": "u_123"})
    assert user["balance"] == 150.0
    assert user["status"] == Status.PROCESSED.value


def test_credits_add_to_the_existing_balance(db):
    add_credit(db, "c1", "u_123", 100.0)
    add_credit(db, "c2", "u_123", 50.0)

    process_credit("c1")
    process_credit("c2")

    assert db.users.find_one({"user_id": "u_123"})["balance"] == 150.0


def test_marks_the_credit_processed(db):
    add_credit(db, "c1", "u_123", 50.0)

    process_credit("c1")

    assert db.credits.find_one({"_id": "c1"})["status"] == Status.PROCESSED.value


def test_only_credits_the_right_user(db):
    add_credit(db, "c1", "u_123", 50.0)
    add_credit(db, "c2", "u_456", 10.0)

    process_credit("c1")

    assert db.users.find_one({"user_id": "u_123"})["balance"] == 50.0
    assert "balance" not in db.users.find_one({"user_id": "u_456"})


def test_unknown_credit_raises(db):
    with pytest.raises(ValueError, match="not found"):
        process_credit("does-not-exist")
