from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List

MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
MILLIONAIRES_COLLECTION = "millionaires"
BIAS_SUMMARIES_COLLECTION = "bias_summaries"


app = FastAPI()
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000","http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
def read_root():
    return {"Hannah smells"}

@app.on_event("startup")
async def startup_db_client():
    app.mongodb_client = AsyncIOMotorClient(MONGO_URI)
    app.mongodb = app.mongodb_client[DB_NAME]

@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()

@app.get("/api/millionaires", response_model=List[dict])
async def get_millionaires():
    collection = app.mongodb[MILLIONAIRES_COLLECTION]
    cursor = collection.find({}, {"_id": 0, "wallet": 1, "balance": 1})
    millionaires = [doc async for doc in cursor]
    return millionaires

@app.get("/api/bias-summaries")
async def get_bias_summaries():
    collection = app.mongodb[BIAS_SUMMARIES_COLLECTION]
    cursor = collection.find({}, {"_id": 0})
    bias_summaries = [doc async for doc in cursor]
    return bias_summaries

@app.get("/api/bias-aggregate")
async def get_bias_aggregate():
    collection = app.mongodb[BIAS_SUMMARIES_COLLECTION]
    cursor = collection.find({}, {"_id": 0, "timestamp": 1, "aggregate": 1})
    aggregates = [doc async for doc in cursor]
    return aggregates

