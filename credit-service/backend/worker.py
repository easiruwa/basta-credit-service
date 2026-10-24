from celery import Celery
from pymongo import MongoClient

from config import settings
from models import Status

celery_app = Celery("credit", broker=settings.redis_url, backend=settings.redis_url)
db = MongoClient(settings.mongo_url)[settings.mongo_db]


@celery_app.task
def process_credit(credit_id: str) -> str:
    credit = db.credits.find_one({"_id": credit_id})

    if not credit:
        raise ValueError(f"Credit with ID {credit_id} not found")

    user_id = credit["user_id"]
    amount = credit["amount"]

    user_update = {"$inc": {"balance": amount}, "$set": {"status": Status.PROCESSED.value}}

    db.users.update_one({"user_id": user_id}, user_update)

    db.credits.update_one({"_id": credit_id}, {"$set": {"status": Status.PROCESSED.value}})

    return credit_id
