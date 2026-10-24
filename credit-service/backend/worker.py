from celery import Celery
from pymongo import MongoClient
from config import settings

celery_app = Celery("credit", broker=settings.redis_url, backend=settings.redis_url)
db = MongoClient(settings.mongo_url)[settings.mongo_db]

@celery_app.task
def process_credit(credit_id: str) -> str:    
    credit = db.credits.find_one({"_id": credit_id})
    user_id = credit.get("user_id")
    amount = credit["amount"]

    db.balances.update_one({"user_id": user_id}, {"$inc": {"balance": amount}}, upsert=True)

    db.credits.update_one({"_id": credit_id}, {"$set": {"status": "processed"}})
    return credit_id