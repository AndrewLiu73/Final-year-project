from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Optional
import os
import time as _time
import logging
from dotenv import load_dotenv
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import httpx
# from biasAlert import compute_watchlist_bias

scheduler = AsyncIOScheduler()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = "hyperliquid"
MILLIONAIRES_COLLECTION = "millionaires"
BIAS_SUMMARIES_COLLECTION = "bias_summaries"
USERS_COLLECTION = "users"
BALANCES_COLLECTION = "balances"
PROFITABILITY_METRICS_COLLECTION = "profitability_metrics"
EXCHANGES_OI_COLLECTION = "exchange_oi"
WATCHLISTS_COLLECTION = "watchlists"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# pulled this out so its not scattered across every endpoint
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"

logger = logging.getLogger("backend")

# simple in-memory cache with TTL — good enough for a single-process server.
# if i ever run multiple uvicorn workers id need redis instead
_cache: Dict[str, dict] = {}

def cache_get(key: str, ttl: int = 300):
    entry = _cache.get(key)
    if entry and (_time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None

def cache_set(key: str, data):
    _cache[key] = {"data": data, "ts": _time.time()}


# lifespan replaces the old @app.on_event("startup") / @app.on_event("shutdown")
# which fastapi deprecated. same idea, just uses a context manager now
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.mongodb_client = AsyncIOMotorClient(MONGO_URI)
    app.mongodb = app.mongodb_client[DB_NAME]
    # shared httpx client for the /live endpoint so we're not creating
    # a new connection on every single request
    app.http_client = httpx.AsyncClient(timeout=10)

    try:
        await app.mongodb[BALANCES_COLLECTION].create_index([("account_balance", 1)])
        await app.mongodb[BALANCES_COLLECTION].create_index([("user", 1)])
        await app.mongodb[BIAS_SUMMARIES_COLLECTION].create_index([("timestamp", -1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("account_value", -1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("total_pnl_usdc", -1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("win_rate_percentage", -1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("max_drawdown_percentage", 1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("open_positions_count", -1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("is_likely_bot", 1)])
        await app.mongodb[PROFITABILITY_METRICS_COLLECTION].create_index([("has_trading_activity", 1)])
        logger.info("indexes created")
    except Exception as e:
        logger.warning(f"index creation: {e}")

    yield

    await app.http_client.aclose()
    app.mongodb_client.close()

app = FastAPI(lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"Root page"}


# these three endpoints barely change so 5 min cache is fine
@app.get("/api/millionaires", response_model=List[dict])
async def get_millionaires():
    cached = cache_get("millionaires", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb[MILLIONAIRES_COLLECTION]
    cursor = collection.find({}, {"_id": 0, "wallet": 1, "balance": 1})
    millionaires = [doc async for doc in cursor]
    cache_set("millionaires", millionaires)
    return millionaires


@app.get("/api/bias-summaries")
async def get_bias_summaries():
    cached = cache_get("bias_summaries", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb[BIAS_SUMMARIES_COLLECTION]
    cursor = collection.find({}, {"_id": 0})
    results = [doc async for doc in cursor]
    cache_set("bias_summaries", results)
    return results


@app.get("/api/bias-aggregate")
async def get_bias_aggregate():
    cached = cache_get("bias_aggregate", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb[BIAS_SUMMARIES_COLLECTION]
    cursor = collection.find({}, {"_id": 0, "timestamp": 1, "aggregate": 1})
    aggregates = [doc async for doc in cursor]
    cache_set("bias_aggregate", aggregates)
    return aggregates


# debug endpoints - handy for checking whats actually in the db
@app.get("/api/debug/sample-doc")
async def debug_sample_doc():
    try:
        coll = app.mongodb[BALANCES_COLLECTION]
        doc = await coll.find_one({}, {"_id": 0})
        return {"sample_doc": doc}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/debug/profitability-sample")
async def debug_profitability_sample():
    try:
        coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]
        doc = await coll.find_one({}, {"_id": 0})
        count = await coll.count_documents({})
        return {"sample_doc": doc, "total_documents": count}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/users/with-balances")
async def get_users_with_balances(
    min_balance: Optional[float] = Query(None, ge=0),
    max_balance: Optional[float] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    sort_by: str = Query("balance", regex="^(balance|wallet)$")
) -> Dict:
    balances_coll = app.mongodb[BALANCES_COLLECTION]

    min_val = min_balance if min_balance is not None else 0
    max_val = max_balance if max_balance is not None else float('inf')

    pipeline = [
        {"$addFields": {
            "balance_float": {
                "$convert": {"input": "$account_balance", "to": "double", "onError": 0, "onNull": 0}
            }
        }},
        {"$match": {"balance_float": {"$gte": min_val, "$lte": max_val}}},
        {"$sort": {"balance_float": -1}},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
        {"$project": {"_id": 0, "wallet": "$user", "currentBalance": "$balance_float"}}
    ]

    count_pipeline = pipeline[:3]
    count_result = await balances_coll.aggregate(count_pipeline + [{"$count": "total"}]).to_list(length=1)
    total_count = count_result[0]["total"] if count_result else 0
    results = await balances_coll.aggregate(pipeline).to_list(length=page_size)

    return {
        "data": results,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_count": total_count,
            "total_pages": (total_count + page_size - 1) // page_size
        }
    }


@app.get("/api/users/profitable")
async def get_profitable_traders(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=10, le=200),
    sort_by: str = Query("pnl"),
    sort_direction: str = Query("desc"),
    min_winrate: float = Query(None),
    max_drawdown: float = Query(None),
    min_balance: float = Query(None),
    max_balance: float = Query(None),
    active_only: bool = Query(False),
    is_bot: str = Query(None),
) -> Dict:
    coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]

    query = {"has_trading_activity": True}

    if min_winrate is not None:
        query["win_rate_percentage"] = {"$gte": min_winrate}
    if max_drawdown is not None:
        query["max_drawdown_percentage"] = {"$lte": max_drawdown}
    if min_balance is not None:
        query.setdefault("account_value", {})["$gte"] = min_balance
    if max_balance is not None:
        query.setdefault("account_value", {})["$lte"] = max_balance
    if active_only:
        query["open_positions_count"] = {"$gt": 0}

    if is_bot == "true":
        query["is_likely_bot"] = True
    elif is_bot == "false":
        query["is_likely_bot"] = {"$ne": True}

    sort_field_map = {
        "pnl": "total_pnl_usdc",
        "balance": "account_value",
        "winrate": "win_rate_percentage",
        "drawdown": "max_drawdown_percentage",
        "openTrades": "open_positions_count",
    }
    field = sort_field_map.get(sort_by, "total_pnl_usdc")
    direction = -1 if sort_direction == "desc" else 1

    total_count = await coll.count_documents(query)
    skip = (page - 1) * page_size

    cursor = coll.find(query, {"_id": 0}).sort(field, direction).skip(skip).limit(page_size)
    docs = await cursor.to_list(length=page_size)

    traders = []
    for doc in docs:
        pnl = doc.get("total_pnl_usdc", 0)
        vol = doc.get("total_volume_usdc", 0)

        traders.append({
            "wallet": doc.get("wallet_address"),
            "currentBalance": doc.get("account_value", 0),
            "withdrawableBalance": doc.get("withdrawable_balance", 0),
            "gainDollar": pnl,
            "gainPercent": round((pnl / vol * 100), 2) if vol > 0 else 0,
            "isProfitable": pnl > 0,
            "winrate": doc.get("win_rate_percentage", 0),
            "maxDrawdown": doc.get("max_drawdown_percentage", 0),
            "tradeCount": doc.get("trade_count", 0),
            "winningTrades": doc.get("winning_trades", 0),
            "losingTrades": doc.get("losing_trades", 0),
            "openPositionsCount": doc.get("open_positions_count", 0),
            "openPositions": doc.get("open_positions", []),
            "totalVolume": vol,
            "avgTradeSize": doc.get("avg_trade_size_usdc", 0),
            "realizedPnl": doc.get("realized_pnl_usdc", 0),
            "unrealizedPnl": doc.get("unrealized_pnl_usdc", 0),
            "userRole": doc.get("user_role", "unknown"),
            "masterWallet": doc.get("master_wallet", None),
            "subAccounts": doc.get("sub_accounts", []),
            "subAccountCount": doc.get("sub_account_count", 0),
            "isLikelyBot": doc.get("is_likely_bot", False),
            "isVaultDepositor": doc.get("is_vault_depositor", False),
            "feeTier": doc.get("fee_tier", 0),
            "userCrossRate": doc.get("user_cross_rate", 0),
            "userAddRate": doc.get("user_add_rate", 0),
            "stakingDiscount": doc.get("staking_discount", 0),
            "historicalPnl": doc.get("historical_pnl", {}),
            "historicalBalance": doc.get("historical_balance", {}),
            "lastUpdated": str(doc.get("last_updated", "")),
        })

    return {
        "data": traders,
        "pagination": {
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "has_more": (skip + len(traders)) < total_count,
        }
    }


@app.get("/api/users/trader/{wallet_address}")
async def get_trader_details(wallet_address: str) -> Dict:
    coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]

    trader = await coll.find_one({"wallet_address": wallet_address}, {"_id": 0})
    if not trader:
        raise HTTPException(status_code=404, detail="Trader not found")

    pnl = trader.get("total_pnl_usdc", 0)
    trades = trader.get("trade_count", 0)
    wins = trader.get("winning_trades", 0)
    losses = trader.get("losing_trades", 0)

    # slap on some computed fields the frontend expects
    trader["total_pnl"] = pnl
    trader["realized_pnl"] = trader.get("realized_pnl_usdc", 0)
    trader["unrealized_pnl"] = trader.get("unrealized_pnl_usdc", 0)
    trader["win_loss_ratio"] = round(wins / losses, 2) if losses > 0 else float(wins)
    trader["avg_profit_per_trade"] = round(pnl / trades, 2) if trades > 0 else 0
    trader["data_source"] = "cached"
    return trader


@app.get("/api/users/trader/{wallet_address}/live")
async def get_trader_live_data(wallet_address: str) -> Dict:
    import asyncio
    from datetime import datetime

    try:
        client = app.http_client

        # fire all 4 calls at once instead of waiting for each one.
        # cuts the response time from ~4x to ~1x the API latency
        state_req = client.post(HYPERLIQUID_API_URL, json={"type": "clearinghouseState", "user": wallet_address})
        portfolio_req = client.post(HYPERLIQUID_API_URL, json={"type": "portfolio", "user": wallet_address})
        spot_req = client.post(HYPERLIQUID_API_URL, json={"type": "spotClearinghouseState", "user": wallet_address})
        mids_req = client.post(HYPERLIQUID_API_URL, json={"type": "allMids"})

        state_resp, portfolio_resp, spot_resp, mids_resp = await asyncio.gather(
            state_req, portfolio_req, spot_req, mids_req
        )

        if state_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch live data from Hyperliquid")

        state = state_resp.json()
        portfolio = portfolio_resp.json() if portfolio_resp.status_code == 200 else []

        margin_summary = state.get('marginSummary', {})
        perp_value = float(margin_summary.get('accountValue', 0))
        withdrawable = float(state.get('withdrawable', 0))

        # calculate spot value from token balances * mid prices
        spot_value = 0.0
        if spot_resp.status_code == 200:
            spot_state = spot_resp.json()
            mids = mids_resp.json() if mids_resp.status_code == 200 else {}
            for b in spot_state.get('balances', []):
                coin = b.get('coin', '')
                total = float(b.get('total', 0))
                if coin == 'USDC':
                    spot_value += total
                elif coin in mids:
                    spot_value += total * float(mids[coin])

        total_account_value = perp_value + spot_value

        # pnl from portfolio
        all_time = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
        pnl_history = all_time.get('pnlHistory', []) if all_time else []
        realized_pnl = float(pnl_history[-1][1]) if pnl_history else 0.0
        total_volume = float(all_time.get('vlm', 0)) if all_time else 0.0

        # live positions
        unrealized_pnl = 0.0
        open_positions = []
        for pos in state.get('assetPositions', []):
            pos_data = pos.get('position', {})
            size = float(pos_data.get('szi', 0))
            if size == 0:
                continue
            upnl = float(pos_data.get('unrealizedPnl', 0))
            unrealized_pnl += upnl
            open_positions.append({
                "asset": pos_data.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pos_data.get('entryPx', 0)),
                "unrealized_pnl": round(upnl, 2)
            })

        total_pnl = realized_pnl + unrealized_pnl
        initial_balance = total_account_value - total_pnl if total_pnl != 0 else total_account_value
        profit_pct = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0

        return {
            "wallet_address": wallet_address,
            "account_value": round(total_account_value, 2),
            "perp_account_value": round(perp_value, 2),
            "spot_account_value": round(spot_value, 2),
            "withdrawable_balance": round(withdrawable, 2),
            "total_pnl": round(total_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "profit_percentage": round(profit_pct, 2),
            "total_volume_usdc": round(total_volume, 2),
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "last_updated": datetime.now().isoformat(),
            "data_source": "live"
        }

    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# 60s cache because OI doesn't change that fast and the aggregation pipeline
# is kinda expensive to run on every page load
@app.get("/api/exchange-oi")
async def get_exchange_oi():
    cached = cache_get("exchange_oi", ttl=60)
    if cached is not None:
        return cached

    pipeline = [
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id": {"coin": "$coin", "exchange": "$exchange"},
            "doc": {"$first": "$$ROOT"}
        }},
        {"$replaceRoot": {"newRoot": "$doc"}}
    ]

    coll = app.mongodb[EXCHANGES_OI_COLLECTION]
    results = await coll.aggregate(pipeline).to_list(length=100)

    grouped = {}
    for doc in results:
        doc["_id"] = str(doc["_id"])
        coin = doc.get("coin", "UNKNOWN")
        if coin not in grouped:
            grouped[coin] = []
        grouped[coin].append({
            "exchange": doc.get("exchange"),
            "oi_usd": doc.get("oi_usd"),
            "mark_px": doc.get("mark_px"),
            "oi_30min_ago": doc.get("oi_30min_ago"),
            "change_pct_30min": doc.get("change_pct_30min"),
            "px_change_30min": doc.get("px_change_30min"),
            "trend_label": doc.get("trend_label"),
            "timestamp": doc.get("timestamp"),
        })

    cache_set("exchange_oi", grouped)
    return grouped


class WatchlistItem(BaseModel):
    user_id: str
    wallet_address: str
    label: str = ""

@app.get("/api/watchlist/{user_id}")
async def get_watchlist(user_id: str):
    col = app.mongodb[WATCHLISTS_COLLECTION]
    cursor = col.find({"user_id": user_id}, {"_id": 0})
    return [doc async for doc in cursor]

@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem):
    col = app.mongodb[WATCHLISTS_COLLECTION]
    existing = await col.find_one({"user_id": item.user_id, "wallet_address": item.wallet_address})
    if existing:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    await col.insert_one(item.model_dump())
    return {"message": "Added to watchlist"}

@app.delete("/api/watchlist/{user_id}/{wallet_address}")
async def remove_from_watchlist(user_id: str, wallet_address: str):
    col = app.mongodb[WATCHLISTS_COLLECTION]
    result = await col.delete_one({"user_id": user_id, "wallet_address": wallet_address})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found in watchlist")
    return {"message": "Removed from watchlist"}

@app.post("/api/users/telegram")
async def save_telegram_id(data: dict):
    users_col = app.mongodb["users"]
    await users_col.update_one(
        {"user_id": data["user_id"]},
        {"$set": {"user_id": data["user_id"], "telegram_id": data["telegram_id"]}},
        upsert=True
    )
    return {"message": "Telegram ID saved"}
