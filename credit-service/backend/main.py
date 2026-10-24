import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from pymongo import AsyncMongoClient

from config import settings
from models import Credit, CreditAccepted, CreditRequest, Status, User
from worker import process_credit

app = FastAPI()
db = AsyncMongoClient(settings.mongo_url)[settings.mongo_db]
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@app.post("/credits", status_code=202, response_model=CreditAccepted)
async def create_credit(payload: CreditRequest):
    credit_id = str(uuid.uuid4())
    user_id = payload.user_id
    amount = payload.amount

    await db.credits.insert_one(
        {
            "_id": credit_id,
            "user_id": user_id,
            "amount": amount,
            "status": Status.PROCESSING.value,
            "created_at": time.time(),
        }
    )
    logger.info("credit %s created for user %s with amount %s", credit_id, user_id, amount)

    await db.users.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": Status.PROCESSING.value,
            },
            "$setOnInsert": {"created_at": time.time()},
        },
        upsert=True,
    )
    logger.info("user %s status set to processing", user_id)

    task = process_credit.delay(credit_id)
    return CreditAccepted(task_id=task.id, credit_id=credit_id, status=Status.PROCESSING.value)


@app.get("/credits/{credit_id}", response_model=Credit)
async def get_credit(credit_id: str):
    credit = await db.credits.find_one({"_id": credit_id})
    if not credit:
        logger.warning("Credit with ID %s not found", credit_id)
        raise HTTPException(status_code=404, detail="Credit not found")
    return Credit(**credit)


@app.get("/users/{user_id}/credits", response_model=list[Credit])
async def get_user_credits(user_id: str):
    if not await db.users.find_one({"user_id": user_id}):
        logger.warning("User with ID %s not found", user_id)
        raise HTTPException(status_code=404, detail="User not found")

    credits_cursor = db.credits.find({"user_id": user_id}).limit(100).sort("created_at", -1)
    credits = [Credit(**credit) async for credit in credits_cursor]
    return credits


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        logger.warning("User with ID %s not found", user_id)
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user)


@app.get("/health")
async def health_check():
    return await db.command("ping")


@app.get("/metrics")
async def metrics():
    cursor = await db.credits.aggregate([{"$group": {"_id": "$status", "count": {"$sum": 1}}}])
    counts = {row["_id"]: row["count"] async for row in cursor}
    total_users = await db.users.count_documents({})

    return {
        "total_credits": sum(counts.values()),
        "processing_credits": counts.get(Status.PROCESSING.value, 0),
        "completed_credits": counts.get(Status.PROCESSED.value, 0),
        "failed_credits": counts.get(Status.FAILED.value, 0),
        "total_users": total_users,
    }
