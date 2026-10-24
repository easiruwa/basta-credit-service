import time
import uuid
from fastapi import FastAPI, HTTPException
from pymongo import AsyncMongoClient
from config import settings
from worker import process_credit

app = FastAPI()
db = AsyncMongoClient(settings.mongo_url)[settings.mongo_db]

@app.post("/credits", status_code=202)
async def create_credit(payload: dict):
    credit_id = str(uuid.uuid4())
    user_id = payload.get("user_id")
    amount = payload.get("amount")

    if not valid_credit_request(user_id, amount):
        raise HTTPException(status_code=400, detail="Invalid credit data")
    
    await db.credits.insert_one({
        "_id": credit_id, 
        "user_id": user_id,
        "amount": amount,
        "status": "processing", 
        "created_at": time.time()})
    process_credit.delay(credit_id)
    return {"id": credit_id, "status": "processing"}


@app.get("/credits/{credit_id}")
async def get_credit(credit_id: str):
    return await db.credits.find_one({"_id": credit_id})


@app.get("/balances/{user_id}")
async def get_balance(user_id: str):
    return await db.balances.find_one({"user_id": user_id})

def valid_credit_request(user_id, amount) -> bool:
    if user_id is None or amount is None:
        return False

    if amount <= 0:
        return False
    
    return True