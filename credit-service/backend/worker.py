from celery import Celery
from pymongo import MongoClient
from config import settings

celery_app = Celery("credit", broker=settings.redis_url, backend=settings.redis_url)
db = MongoClient(settings.mongo_url)[settings.mongo_db]

@celery_app.task
def process_application(app_id: str) -> str:
    db.applications.update_one({"_id": app_id}, {"$set": {"status": "processed"}})
    return app_id