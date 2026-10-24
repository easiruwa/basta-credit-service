import time
import uuid
from fastapi import FastAPI, HTTPException
from pymongo import AsyncMongoClient
from config import settings
from worker import process_credit
from models import CreditRequest, Status, User, Credit


app = FastAPI()
db = AsyncMongoClient(settings.mongo_url)[settings.mongo_db]


@app.post("/credits", status_code=202)
async def create_credit(payload: CreditRequest):
    credit_id = str(uuid.uuid4())
    user_id = payload.user_id
    amount = payload.amount
    
    await db.credits.insert_one({
        "_id": credit_id, 
        "user_id": user_id,
        "amount": amount,
        "status": Status.PROCESSING.value, 
        "created_at": time.time()})

    await db.users.update_one({
        "user_id": user_id
    }, {
        "$set": {
            "status": Status.PROCESSING.value, 
        },
        "$setOnInsert": {
            "created_at":  time.time()
        }
    }, upsert=True)

    process_credit.delay(credit_id)
    return {"id": credit_id, "status": Status.PROCESSING.value}


@app.get("/credits/{credit_id}", response_model=Credit)
async def get_credit(credit_id: str):
    credit = await db.credits.find_one({"_id": credit_id})
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found")
    return Credit(**credit)


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: str):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return User(**user)
