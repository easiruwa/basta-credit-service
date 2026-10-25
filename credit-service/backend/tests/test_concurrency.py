"""Many workers crediting the same user at the same time.

In production several Celery processes run tasks in parallel, so credits for one
user can be applied at the same moment. These tests run the task from many
threads at once against the real database.
"""

from concurrent.futures import ThreadPoolExecutor

from models import Status
from test_worker import add_credit
from worker import process_credit

CREDITS = 50
AMOUNT = 10.0
THREADS = 16


def run_concurrently(credit_ids):
    with ThreadPoolExecutor(max_workers=THREADS) as pool:
        # list() waits for every task and re-raises any error from a thread.
        list(pool.map(process_credit, credit_ids))


def test_concurrent_credits_all_land(db):
    credit_ids = [f"c{i}" for i in range(CREDITS)]
    for credit_id in credit_ids:
        add_credit(db, credit_id, "u_123", AMOUNT)

    run_concurrently(credit_ids)

    user = db.users.find_one({"user_id": "u_123"})
    assert user["balance"] == CREDITS * AMOUNT
    assert user["status"] == Status.PROCESSED.value
    assert sorted(user["applied_credits"]) == sorted(credit_ids)
    assert db.credits.count_documents({"status": Status.PROCESSED.value}) == CREDITS


def test_concurrent_duplicates_still_apply_each_credit_once(db):
    credit_ids = [f"c{i}" for i in range(CREDITS)]
    for credit_id in credit_ids:
        add_credit(db, credit_id, "u_123", AMOUNT)

    # Every credit is delivered three times, and the copies race each other.
    run_concurrently(credit_ids * 3)

    user = db.users.find_one({"user_id": "u_123"})
    assert user["balance"] == CREDITS * AMOUNT
    assert len(user["applied_credits"]) == CREDITS
