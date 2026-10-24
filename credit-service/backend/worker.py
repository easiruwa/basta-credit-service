from celery import Celery
from celery.utils.log import get_task_logger
from pymongo import MongoClient

from config import settings
from models import Status

celery_app = Celery("credit", broker=settings.redis_url, backend=settings.redis_url)
db = MongoClient(settings.mongo_url)[settings.mongo_db]
logger = get_task_logger(__name__)


@celery_app.task(acks_late=True, max_retries=5, name="ProcessUserCredit")
def process_credit(credit_id: str) -> str:
    credit = db.credits.find_one({"_id": credit_id})

    if not credit:
        logger.error("Credit with ID %s not found", credit_id)
        raise ValueError(f"Credit with ID {credit_id} not found")

    user_id = credit["user_id"]
    amount = credit["amount"]

    user_update = {
        "$inc": {"balance": amount},
        "$set": {"status": Status.PROCESSED.value},
        "$push": {"applied_credits": credit_id},
    }

    modified_count = db.users.update_one(
        {"user_id": user_id, "applied_credits": {"$ne": credit_id}}, user_update
    ).modified_count

    if modified_count == 0:
        logger.warning("Credit %s already applied to user %s", credit_id, user_id)

    db.credits.update_one({"_id": credit_id}, {"$set": {"status": Status.PROCESSED.value}})

    logger.info("Applied credit %s to user %s", credit_id, user_id)

    return credit_id
