import uuid
from fastapi import FastAPI
from pymongo import AsyncMongoClient
from config import settings
from worker import process_application

app = FastAPI()
db = AsyncMongoClient(settings.mongo_url)[settings.mongo_db]

@app.post("/applications")
async def create_application(payload: dict):
    app_id = str(uuid.uuid4())
    await db.applications.insert_one({"_id": app_id, **payload, "status": "pending"})
    process_application.delay(app_id)
    return {"id": app_id, "status": "pending"}

@app.get("/applications/{app_id}")
async def get_application(app_id: str):
    return await db.applications.find_one({"_id": app_id})