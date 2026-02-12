from fastapi import FastAPI,Query
from motor.motor_asyncio import AsyncIOMotorClient
import asyncio
from typing import List,Dict,Optional
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
    allow_origins=["http://127.0.0.1:8000","http://localhost:3000"],
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


from typing import List, Dict

@app.get("/api/debug/sample-doc")
async def debug_sample_doc():
    try:
        balances_coll = app.mongodb[BALANCES_COLLECTION]
        doc = await balances_coll.find_one({}, {"_id": 0})  # Exclude _id
        return {"sample_doc": doc}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/users/with-balances")
async def get_users_with_balances(
        min_balance: Optional[float] = Query(None, ge=0),
        max_balance: Optional[float] = Query(None, ge=0),
) -> List[Dict]:
    balances_coll = app.mongodb[DB_NAME][BALANCES_COLLECTION]

    # Fetch all docs without _id
    docs = await balances_coll.find({}, {"_id": 0}).to_list(length=None)

    # Set defaults
    min_val = min_balance if min_balance is not None else 0
    max_val = max_balance if max_balance is not None else float('inf')

    result: List[Dict] = []

    for doc in docs:
        wallet = doc.get("user")
        balance_str = doc.get("account_balance", "0")

        # Convert string balance to float
        try:
            current_balance = float(balance_str)
        except (ValueError, TypeError):
            current_balance = 0

        # Filter by range
        if current_balance < min_val or current_balance > max_val:
            continue

        result.append({
            "wallet": wallet,
            "currentBalance": current_balance,
            "isProfitable": current_balance > 0,
        })

    return result



