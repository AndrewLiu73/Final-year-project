from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Optional
import os
import time as _time
import logging
from dotenv import load_dotenv
from pydantic import BaseModel
import httpx


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

MONGO_URI = os.getenv("MONGO_URI")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# pulled this out so its not scattered across every endpoint
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"

logger = logging.getLogger("backend")

# simple in-memory cache with TTL — good enough for a single-process server.
# if i ever run multiple uvicorn workers id need redis instead
_cache: Dict[str, dict] = {}

def cacheGet(key: str, ttl: int = 300):
    entry = _cache.get(key)
    if entry and (_time.time() - entry["ts"]) < ttl:
        return entry["data"]
    return None

def cacheSet(key: str, data):
    _cache[key] = {"data": data, "ts": _time.time()}


# lifespan replaces the old @app.on_event("startup") / @app.on_event("shutdown")
# which fastapi deprecated. same idea, just uses a context manager now
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.mongodb_client = AsyncIOMotorClient(MONGO_URI)
    app.mongodb = app.mongodb_client["hyperliquid"]
    # shared httpx client for the /live endpoint so we're not creating
    # a new connection on every single request
    app.http_client = httpx.AsyncClient(timeout=10)
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
def readRoot():
    return {"Root page"}


# these three endpoints barely change so 5 min cache is fine
@app.get("/api/millionaires", response_model=List[dict])
async def getMillionaires():
    cached = cacheGet("millionaires", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb["millionaires"]
    cursor = collection.find({}, {"_id": 0, "wallet": 1, "balance": 1})
    millionaires = [doc async for doc in cursor]
    cacheSet("millionaires", millionaires)
    return millionaires


@app.get("/api/bias-summaries")
async def getBiasSummaries():
    cached = cacheGet("bias_summaries", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb["bias_summaries"]
    cursor = collection.find({}, {"_id": 0})
    results = [doc async for doc in cursor]
    cacheSet("bias_summaries", results)
    return results


@app.get("/api/bias-aggregate")
async def getBiasAggregate():
    cached = cacheGet("bias_aggregate", ttl=300)
    if cached is not None:
        return cached

    collection = app.mongodb["bias_summaries"]
    cursor = collection.find({}, {"_id": 0, "timestamp": 1, "aggregate": 1})
    aggregates = [doc async for doc in cursor]
    cacheSet("bias_aggregate", aggregates)
    return aggregates


# debug endpoints - handy for checking whats actually in the db
@app.get("/api/debug/sample-doc")
async def debugSampleDoc():
    try:
        coll = app.mongodb["balances"]
        doc = await coll.find_one({}, {"_id": 0})
        return {"sample_doc": doc}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/debug/profitability-sample")
async def debugProfitabilitySample():
    try:
        coll = app.mongodb["profitability_metrics"]
        doc = await coll.find_one({}, {"_id": 0})
        count = await coll.count_documents({})
        return {"sample_doc": doc, "total_documents": count}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/users/with-balances")
async def getUsersWithBalances(
    minBalance: Optional[float] = Query(None, ge=0),
    maxBalance: Optional[float] = Query(None, ge=0),
    page: int = Query(1, ge=1),
    pageSize: int = Query(100, ge=1, le=500),
    sortBy: str = Query("balance", regex="^(balance|wallet)$")
) -> Dict:
    balancesColl = app.mongodb["balances"]

    minVal = minBalance if minBalance is not None else 0
    maxVal = maxBalance if maxBalance is not None else float('inf')

    pipeline = [
        {"$addFields": {
            "balance_float": {
                "$convert": {"input": "$account_balance", "to": "double", "onError": 0, "onNull": 0}
            }
        }},
        {"$match": {"balance_float": {"$gte": minVal, "$lte": maxVal}}},
        {"$sort": {"balance_float": -1}},
        {"$skip": (page - 1) * pageSize},
        {"$limit": pageSize},
        {"$project": {"_id": 0, "wallet": "$user", "currentBalance": "$balance_float"}}
    ]

    countPipeline = pipeline[:3]
    countResult = await balancesColl.aggregate(countPipeline + [{"$count": "total"}]).to_list(length=1)
    totalCount = countResult[0]["total"] if countResult else 0
    results = await balancesColl.aggregate(pipeline).to_list(length=pageSize)

    return {
        "data": results,
        "pagination": {
            "page": page,
            "page_size": pageSize,
            "total_count": totalCount,
            "total_pages": (totalCount + pageSize - 1) // pageSize
        }
    }


@app.get("/api/users/profitable")
async def getProfitableTraders(
    page: int = Query(1, ge=1),
    pageSize: int = Query(100, ge=10, le=200),
    sortBy: str = Query("pnl"),
    sortDirection: str = Query("desc"),
    minWinrate: float = Query(None),
    maxDrawdown: float = Query(None),
    minBalance: float = Query(None),
    maxBalance: float = Query(None),
    activeOnly: bool = Query(False),
    isBot: str = Query(None),
) -> Dict:
    coll = app.mongodb["profitability_metrics"]

    query = {"has_trading_activity": True}

    if minWinrate is not None:
        query["win_rate_percentage"] = {"$gte": minWinrate}
    if maxDrawdown is not None:
        query["max_drawdown_percentage"] = {"$lte": maxDrawdown}
    if minBalance is not None:
        query.setdefault("account_value", {})["$gte"] = minBalance
    if maxBalance is not None:
        query.setdefault("account_value", {})["$lte"] = maxBalance
    if activeOnly:
        query["open_positions_count"] = {"$gt": 0}

    if isBot == "true":
        query["is_likely_bot"] = True
    elif isBot == "false":
        query["is_likely_bot"] = {"$ne": True}

    sortFieldMap = {
        "pnl": "total_pnl_usdc",
        "balance": "account_value",
        "winrate": "win_rate_percentage",
        "drawdown": "max_drawdown_percentage",
        "openTrades": "open_positions_count",
    }
    field = sortFieldMap.get(sortBy, "total_pnl_usdc")
    direction = -1 if sortDirection == "desc" else 1

    totalCount = await coll.count_documents(query)
    skip = (page - 1) * pageSize

    cursor = coll.find(query, {"_id": 0}).sort(field, direction).skip(skip).limit(pageSize)
    docs = await cursor.to_list(length=pageSize)

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
            "total_count": totalCount,
            "page": page,
            "page_size": pageSize,
            "has_more": (skip + len(traders)) < totalCount,
        }
    }


@app.get("/api/users/trader/{walletAddress}")
async def getTraderDetails(walletAddress: str) -> Dict:
    coll = app.mongodb["profitability_metrics"]

    trader = await coll.find_one({"wallet_address": walletAddress}, {"_id": 0})
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


@app.get("/api/users/trader/{walletAddress}/live")
async def getTraderLiveData(walletAddress: str) -> Dict:
    import asyncio
    from datetime import datetime

    try:
        client = app.http_client

        # fire all 4 calls at once instead of waiting for each one.
        # cuts the response time from ~4x to ~1x the API latency
        stateReq = client.post(HYPERLIQUID_API_URL, json={"type": "clearinghouseState", "user": walletAddress})
        portfolioReq = client.post(HYPERLIQUID_API_URL, json={"type": "portfolio", "user": walletAddress})
        spotReq = client.post(HYPERLIQUID_API_URL, json={"type": "spotClearinghouseState", "user": walletAddress})
        midsReq = client.post(HYPERLIQUID_API_URL, json={"type": "allMids"})

        stateResp, portfolioResp, spotResp, midsResp = await asyncio.gather(
            stateReq, portfolioReq, spotReq, midsReq
        )

        if stateResp.status_code != 200:
            raise HTTPException(status_code=502, detail="Failed to fetch live data from Hyperliquid")

        state = stateResp.json()
        portfolio = portfolioResp.json() if portfolioResp.status_code == 200 else []

        marginSummary = state.get('marginSummary', {})
        perpValue = float(marginSummary.get('accountValue', 0))
        withdrawable = float(state.get('withdrawable', 0))

        # calculate spot value from token balances * mid prices
        spotValue = 0.0
        if spotResp.status_code == 200:
            spotState = spotResp.json()
            mids = midsResp.json() if midsResp.status_code == 200 else {}
            for b in spotState.get('balances', []):
                coin = b.get('coin', '')
                total = float(b.get('total', 0))
                if coin == 'USDC':
                    spotValue += total
                elif coin in mids:
                    spotValue += total * float(mids[coin])

        totalAccountValue = perpValue + spotValue

        # pnl from portfolio
        allTime = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
        pnlHistory = allTime.get('pnlHistory', []) if allTime else []
        realizedPnl = float(pnlHistory[-1][1]) if pnlHistory else 0.0
        totalVolume = float(allTime.get('vlm', 0)) if allTime else 0.0

        # live positions
        unrealizedPnl = 0.0
        openPositions = []
        for pos in state.get('assetPositions', []):
            posData = pos.get('position', {})
            size = float(posData.get('szi', 0))
            if size == 0:
                continue
            upnl = float(posData.get('unrealizedPnl', 0))
            unrealizedPnl += upnl
            openPositions.append({
                "asset": posData.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(posData.get('entryPx', 0)),
                "unrealized_pnl": round(upnl, 2)
            })

        totalPnl = realizedPnl + unrealizedPnl
        initialBalance = totalAccountValue - totalPnl if totalPnl != 0 else totalAccountValue
        profitPct = (totalPnl / initialBalance * 100) if initialBalance > 0 else 0

        return {
            "wallet_address": walletAddress,
            "account_value": round(totalAccountValue, 2),
            "perp_account_value": round(perpValue, 2),
            "spot_account_value": round(spotValue, 2),
            "withdrawable_balance": round(withdrawable, 2),
            "total_pnl": round(totalPnl, 2),
            "realized_pnl": round(realizedPnl, 2),
            "unrealized_pnl": round(unrealizedPnl, 2),
            "profit_percentage": round(profitPct, 2),
            "total_volume_usdc": round(totalVolume, 2),
            "open_positions": openPositions,
            "open_positions_count": len(openPositions),
            "last_updated": datetime.now().isoformat(),
            "data_source": "live"
        }

    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# 60s cache because OI doesn't change that fast and the aggregation pipeline
# is kinda expensive to run on every page load
@app.get("/api/exchange-oi")
async def getExchangeOi():
    cached = cacheGet("exchange_oi", ttl=60)
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

    coll = app.mongodb["exchange_oi"]
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

    cacheSet("exchange_oi", grouped)
    return grouped


@app.get("/api/large-positions")
async def getLargePositions(
    minNotionalUsd: Optional[float] = Query(10000, ge=0),
    asset: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    sortBy: str = Query("notional_usd"),
    sortDirection: str = Query("desc"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=500),
):
    """
    Reads from the open_positions collection which OpenTrades.py keeps fresh.
    """
    cacheKey = f"large_pos:{minNotionalUsd}:{asset}:{direction}:{sortBy}:{sortDirection}:{page}:{pageSize}"
    cached = cacheGet(cacheKey, ttl=30)
    if cached is not None:
        return cached

    coll = app.mongodb["open_positions"]

    query = {}
    if minNotionalUsd:
        query["notional_usd"] = {"$gte": minNotionalUsd}
    if asset:
        query["asset"] = asset.upper()
    if direction:
        query["direction"] = direction.upper()

    sortFieldMap = {
        "notional_usd": "notional_usd",
        "unrealized_pnl": "unrealized_pnl",
        "account_value": "account_value",
        "size": "size",
    }
    field = sortFieldMap.get(sortBy, "notional_usd")
    mongoDir = -1 if sortDirection == "desc" else 1

    totalCount = await coll.count_documents(query)
    unique_wallets = len(await coll.distinct("wallet_address", query))
    skip = (page - 1) * pageSize

    cursor = coll.find(query, {"_id": 0}).sort(field, mongoDir).skip(skip).limit(pageSize)
    results = await cursor.to_list(length=pageSize)

    for r in results:
        if r.get("last_updated") and hasattr(r["last_updated"], "isoformat"):
            r["last_updated"] = r["last_updated"].isoformat()

    response = {
        "data": results,
        "pagination": {
            "total_count": totalCount,
            "unique_wallets": unique_wallets,
            "page": page,
            "page_size": pageSize,
            "has_more": (skip + len(results)) < totalCount,
        }
    }

    cacheSet(cacheKey, response)
    return response


@app.get("/api/asset-concentration")
async def getAssetConcentration():
    """
    Read asset concentration from the pre-computed asset_concentration collection.
    """
    cached = cacheGet("asset_concentration", ttl=30)
    if cached is not None:
        return cached

    coll = app.mongodb["asset_concentration"]
    cursor = coll.find({}, {"_id": 0}).sort("total_notional", -1)
    results = await cursor.to_list(length=200)

    for r in results:
        if r.get("last_updated") and hasattr(r["last_updated"], "isoformat"):
            r["last_updated"] = r["last_updated"].isoformat()

    cacheSet("asset_concentration", results)
    return results


class WatchlistItem(BaseModel):
    userId: str
    walletAddress: str
    label: str = ""

@app.get("/api/watchlist/{userId}")
async def getWatchlist(userId: str):
    col = app.mongodb["watchlists"]
    cursor = col.find({"user_id": userId}, {"_id": 0})
    return [doc async for doc in cursor]

@app.post("/api/watchlist")
async def addToWatchlist(item: WatchlistItem):
    col = app.mongodb["watchlists"]
    existing = await col.find_one({"user_id": item.userId, "wallet_address": item.walletAddress})
    if existing:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    await col.insert_one({"user_id": item.userId, "wallet_address": item.walletAddress, "label": item.label})
    return {"message": "Added to watchlist"}

@app.delete("/api/watchlist/{userId}/{walletAddress}")
async def removeFromWatchlist(userId: str, walletAddress: str):
    col = app.mongodb["watchlists"]
    result = await col.delete_one({"user_id": userId, "wallet_address": walletAddress})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found in watchlist")
    return {"message": "Removed from watchlist"}

@app.post("/api/users/telegram")
async def saveTelegramId(data: dict):
    usersCol = app.mongodb["users"]
    await usersCol.update_one(
        {"user_id": data["userId"]},
        {"$set": {"user_id": data["userId"], "telegram_id": data["telegramId"]}},
        upsert=True
    )
    return {"message": "Telegram ID saved"}
