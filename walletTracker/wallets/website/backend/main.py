from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List
from typing import Dict
import os
from dotenv import load_dotenv
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "hyperliquid"
MILLIONAIRES_COLLECTION = "millionaires"
BIAS_SUMMARIES_COLLECTION = "bias_summaries"
USERS_COLLECTION = "users"
BALANCES_COLLECTION = "balances"


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


@app.get("/api/users/with-balances")
async def get_users_with_balances(min_gain_percent: float = 0, max_gain_percent: float = 1000) -> List[Dict]:
    users_coll = app.mongodb[USERS_COLLECTION]
    balances_coll = app.mongodb[BALANCES_COLLECTION]
    millionaires_coll = app.mongodb[MILLIONAIRES_COLLECTION]

    # 1. Fetch ALL data in parallel (much faster)
    # Using to_list with length=None to get all docs at once
    users_task = users_coll.find({}, {"_id": 0, "user": 1}).to_list(length=None)
    balances_task = balances_coll.find({}, {"_id": 0, "user": 1, "account_balance": 1}).to_list(length=None)
    millionaires_task = millionaires_coll.find({}, {"_id": 0, "wallet": 1, "balance": 1}).to_list(length=None)

    # Run all 3 queries at the same time
    users, balances, millionaires = await asyncio.gather(users_task, balances_task, millionaires_task)

    # 2. Create lookups (Hash Maps) for instant access O(1)
    balance_map = {b['user']: float(b['account_balance']) for b in balances}
    millionaire_map = {m['wallet']: float(m['balance']) for m in millionaires}

    result = []

    # 3. Join data in memory (Instant)
    for u in users:
        wallet = u['user']

        # Fast lookup
        current_balance = balance_map.get(wallet, 0.0)
        initial_balance = millionaire_map.get(wallet, 1.0)  # Avoid div by zero

        if initial_balance == 0: initial_balance = 1.0

        gain_percent = ((current_balance / initial_balance) * 100)
        gain_dollar = current_balance - initial_balance

        # Filter logic here (Server-side filtering is faster!)
        if min_gain_percent <= gain_percent <= max_gain_percent:
            result.append({
                "wallet": wallet,
                "currentBalance": current_balance,
                "initialBalance": initial_balance,
                "gainPercent": gain_percent,
                "gainDollar": gain_dollar,
                "isProfitable": gain_dollar > 0
            })

    return result

