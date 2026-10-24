"""The full spec flow: API request, then the worker, then the user document."""

from models import Status
from worker import process_credit


def test_post_then_process_produces_the_spec_document(client, queued):
    client.post("/credits", json={"user_id": "u_123", "amount": 100})
    client.post("/credits", json={"user_id": "u_123", "amount": 50})

    # Run whatever the API queued, the way the Celery worker would.
    for call in queued.call_args_list:
        process_credit(*call.args)

    user = client.get("/users/u_123").json()
    assert user["user_id"] == "u_123"
    assert user["balance"] == 150.0
    assert user["status"] == Status.PROCESSED.value
