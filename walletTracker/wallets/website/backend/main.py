from fastapi import FastAPI, Query, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv
from pydantic import BaseModel
import hashlib
import hmac
import time
import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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
app = FastAPI()

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


@app.on_event("startup")
async def startup_db_client():
    app.mongodb_client = AsyncIOMotorClient(MONGO_URI)
    app.mongodb = app.mongodb_client[DB_NAME]

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
        print("indexes created")
    except Exception as e:
        print(f"index creation: {e}")

        # scheduler.add_job(
        #     compute_watchlist_bias,
        #     "interval",
        #     minutes=15,
        #     args=[app.mongodb]
        # )
        # scheduler.start()


@app.on_event("shutdown")
async def shutdown_db_client():
    app.mongodb_client.close()
    # scheduler.shutdown()


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


@app.get("/api/debug/sample-doc")
async def debug_sample_doc():
    try:
        balances_coll = app.mongodb[BALANCES_COLLECTION]
        doc = await balances_coll.find_one({}, {"_id": 0})
        return {"sample_doc": doc}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/debug/profitability-sample")
async def debug_profitability_sample():
    try:
        profitability_coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]
        doc   = await profitability_coll.find_one({}, {"_id": 0})
        count = await profitability_coll.count_documents({})
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
        {
            "$addFields": {
                "balance_float": {
                    "$convert": {
                        "input": "$account_balance",
                        "to": "double",
                        "onError": 0,
                        "onNull": 0
                    }
                }
            }
        },
        {"$match": {"balance_float": {"$gte": min_val, "$lte": max_val}}},
        {"$sort": {"balance_float": -1}},
        {"$skip": (page - 1) * page_size},
        {"$limit": page_size},
        {"$project": {"_id": 0, "wallet": "$user", "currentBalance": "$balance_float"}}
    ]

    count_pipeline  = pipeline[:3]
    count_result    = await balances_coll.aggregate(count_pipeline + [{"$count": "total"}]).to_list(length=1)
    total_count     = count_result[0]["total"] if count_result else 0
    results         = await balances_coll.aggregate(pipeline).to_list(length=page_size)

    return {
        "data": results,
        "pagination": {
            "page":        page,
            "page_size":   page_size,
            "total_count": total_count,
            "total_pages": (total_count + page_size - 1) // page_size
        }
    }


@app.get("/api/users/profitable")
async def get_profitable_traders(
    page:           int   = Query(1,     ge=1),
    page_size:      int   = Query(100,   ge=10, le=200),
    sort_by:        str   = Query("pnl"),
    sort_direction: str   = Query("desc"),
    min_winrate:    float = Query(None),
    max_drawdown:   float = Query(None),
    min_balance:    float = Query(None),
    max_balance:    float = Query(None),
    active_only:    bool  = Query(False),
    is_bot:         str   = Query(None),   # "true", "false", or None
) -> Dict:
    profitability_coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]

    query = {"has_trading_activity": True}

    if min_winrate  is not None: query["win_rate_percentage"]    = {"$gte": min_winrate}
    if max_drawdown is not None: query["max_drawdown_percentage"] = {"$lte": max_drawdown}
    if min_balance  is not None: query.setdefault("account_value", {})["$gte"] = min_balance
    if max_balance  is not None: query.setdefault("account_value", {})["$lte"] = max_balance
    if active_only:              query["open_positions_count"]    = {"$gt": 0}

    # bot filter
    if is_bot == "true":
        query["is_likely_bot"] = True
    elif is_bot == "false":
        query["is_likely_bot"] = {"$ne": True}

    sort_field_map = {
        "pnl":        "total_pnl_usdc",
        "balance":    "account_value",
        "winrate":    "win_rate_percentage",
        "drawdown":   "max_drawdown_percentage",
        "openTrades": "open_positions_count",
    }
    sort_field = sort_field_map.get(sort_by, "total_pnl_usdc")
    sort_dir   = -1 if sort_direction == "desc" else 1

    total_count = await profitability_coll.count_documents(query)
    skip        = (page - 1) * page_size

    cursor = profitability_coll.find(query, {"_id": 0}).sort(sort_field, sort_dir).skip(skip).limit(page_size)
    docs   = await cursor.to_list(length=page_size)

    traders = []
    for doc in docs:
        total_pnl    = doc.get("total_pnl_usdc",  0)
        total_volume = doc.get("total_volume_usdc", 0)
        account_val  = doc.get("account_value",    0)

        traders.append({
            "wallet":              doc.get("wallet_address"),
            "currentBalance":      account_val,
            "withdrawableBalance": doc.get("withdrawable_balance", 0),
            "gainDollar":          total_pnl,
            "gainPercent":         round((total_pnl / total_volume * 100), 2) if total_volume > 0 else 0,
            "isProfitable":        total_pnl > 0,
            "winrate":             doc.get("win_rate_percentage",    0),
            "maxDrawdown":         doc.get("max_drawdown_percentage", 0),
            "tradeCount":          doc.get("trade_count",            0),
            "winningTrades":       doc.get("winning_trades",         0),
            "losingTrades":        doc.get("losing_trades",          0),
            "openPositionsCount":  doc.get("open_positions_count",   0),
            "openPositions":       doc.get("open_positions",         []),
            "totalVolume":         doc.get("total_volume_usdc",      0),
            "avgTradeSize":        doc.get("avg_trade_size_usdc",    0),
            "realizedPnl":         doc.get("realized_pnl_usdc",      0),
            "unrealizedPnl":       doc.get("unrealized_pnl_usdc",    0),
            "userRole":            doc.get("user_role",              "unknown"),
            "masterWallet":        doc.get("master_wallet",          None),
            "subAccounts":         doc.get("sub_accounts",           []),
            "subAccountCount":     doc.get("sub_account_count",      0),
            "isLikelyBot":         doc.get("is_likely_bot",          False),
            "isVaultDepositor":    doc.get("is_vault_depositor",     False),
            "feeTier":             doc.get("fee_tier",               0),
            "userCrossRate":       doc.get("user_cross_rate",        0),
            "userAddRate":         doc.get("user_add_rate",          0),
            "stakingDiscount":     doc.get("staking_discount",       0),
            "historicalPnl":       doc.get("historical_pnl",         {}),
            "historicalBalance":   doc.get("historical_balance",     {}),
            "lastUpdated":         str(doc.get("last_updated",       "")),
        })

    return {
        "data": traders,
        "pagination": {
            "total_count": total_count,
            "page":        page,
            "page_size":   page_size,
            "has_more":    (skip + len(traders)) < total_count,
        }
    }

@app.get("/api/users/trader/{wallet_address}")
async def get_trader_details(wallet_address: str) -> Dict:
    """
    Cached trader data from the scanner.
    Source of truth for trade history stats (win rate, drawdown, trade count).
    These require full fill history which only the scanner has.
    """
    profitability_coll = app.mongodb[PROFITABILITY_METRICS_COLLECTION]

    trader = await profitability_coll.find_one(
        {"wallet_address": wallet_address},
        {"_id": 0}
    )

    if not trader:
        return {"error": "Trader not found", "wallet": wallet_address}

    total_pnl       = trader.get("total_pnl_usdc", 0)
    account_val     = trader.get("account_value",  0)
    winning_trades  = trader.get("winning_trades", 0)
    losing_trades   = trader.get("losing_trades",  0)
    trade_count     = trader.get("trade_count",    0)

    win_loss_ratio       = winning_trades / losing_trades if losing_trades > 0 else float(winning_trades)
    avg_profit_per_trade = total_pnl / trade_count if trade_count > 0 else 0

    return {
        "wallet_address": wallet_address,
        "account_value": account_val,
        "withdrawable_balance": trader.get("withdrawable_balance", 0),

        # pnl
        "total_pnl": total_pnl,
        "realized_pnl": trader.get("realized_pnl_usdc", 0),
        "unrealized_pnl": trader.get("unrealized_pnl_usdc", 0),
        "profit_percentage": trader.get("profit_percentage", 0),

        # trade history
        "win_rate_percentage": trader.get("win_rate_percentage", 0),
        "trade_count": trade_count,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_loss_ratio": round(win_loss_ratio, 2),
        "avg_profit_per_trade": round(avg_profit_per_trade, 2),
        "max_drawdown_percentage": trader.get("max_drawdown_percentage", 0),

        # volume
        "total_volume_usdc": trader.get("total_volume_usdc", 0),
        "avg_trade_size_usdc": trader.get("avg_trade_size_usdc", 0),

        # positions
        "open_positions": trader.get("open_positions", []),
        "open_positions_count": trader.get("open_positions_count", 0),


        "user_role": trader.get("user_role", "unknown"),
        "master_wallet": trader.get("master_wallet", None),
        "sub_accounts": trader.get("sub_accounts", []),
        "sub_account_count": trader.get("sub_account_count", 0),
        "has_trading_activity": trader.get("has_trading_activity", False),
        "last_updated": trader.get("last_updated", None),
        "historical_pnl": trader.get("historical_pnl", {}),
        "historical_balance": trader.get("historical_balance", {}),
        "data_source": "cached"
    }


@app.get("/api/users/trader/{wallet_address}/live")
async def get_trader_live_data(wallet_address: str) -> Dict:
    """
    Real-time fields only - no fills fetched.
    Fetches clearinghouseState + portfolio only (~300ms).
    Returns: account value, open positions, unrealized pnl, realized pnl, total volume.
    Trade history stats (win rate, drawdown etc) come from the DB endpoint - not here.
    """
    import requests
    from datetime import datetime

    try:
        # fire both requests - neither touches fills
        state_resp     = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "clearinghouseState", "user": wallet_address},
            timeout=10
        )
        portfolio_resp = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "portfolio", "user": wallet_address},
            timeout=10
        )

        if state_resp.status_code != 200:
            return {"error": "Failed to fetch live data from Hyperliquid"}

        state     = state_resp.json()
        portfolio = portfolio_resp.json() if portfolio_resp.status_code == 200 else []

        margin_summary = state.get('marginSummary', {})
        account_value  = float(margin_summary.get('accountValue', 0))
        withdrawable   = float(state.get('withdrawable', 0))

        # all-time realized pnl and volume from portfolio - accurate without fills
        all_time     = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
        pnl_history  = all_time.get('pnlHistory', []) if all_time else []
        realized_pnl = float(pnl_history[-1][1]) if pnl_history else 0.0
        total_volume = float(all_time.get('vlm', 0)) if all_time else 0.0

        # live open positions and unrealized pnl from clearinghouseState
        unrealized_pnl = 0.0
        open_positions = []

        for pos in state.get('assetPositions', []):
            pos_data  = pos.get('position', {})
            size      = float(pos_data.get('szi', 0))

            if size == 0:
                continue

            pos_upnl        = float(pos_data.get('unrealizedPnl', 0))
            unrealized_pnl += pos_upnl

            open_positions.append({
                "asset":          pos_data.get('coin', 'UNKNOWN'),
                "direction":      "LONG" if size > 0 else "SHORT",
                "size":           abs(size),
                "entry_price":    float(pos_data.get('entryPx', 0)),
                "unrealized_pnl": round(pos_upnl, 2)
            })

        total_pnl         = realized_pnl + unrealized_pnl
        initial_balance   = account_value - total_pnl if total_pnl != 0 else account_value
        profit_percentage = (total_pnl / initial_balance * 100) if initial_balance > 0 else 0

        return {
            "wallet_address":       wallet_address,
            "account_value":        round(account_value, 2),
            "withdrawable_balance": round(withdrawable, 2),

            # pnl - live and accurate
            "total_pnl":          round(total_pnl, 2),
            "realized_pnl":       round(realized_pnl, 2),
            "unrealized_pnl":     round(unrealized_pnl, 2),
            "profit_percentage":  round(profit_percentage, 2),
            "total_volume_usdc":  round(total_volume, 2),

            # positions - live
            "open_positions":       open_positions,
            "open_positions_count": len(open_positions),

            "last_updated": datetime.now().isoformat(),
            "data_source":  "live"
        }

    except Exception as e:
        return {"error": str(e), "wallet_address": wallet_address}

@app.get("/api/exchange-oi")
async def get_exchange_oi():
    pipeline = [
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": {"coin": "$coin", "exchange": "$exchange"},
                "doc": {"$first": "$$ROOT"}
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}}
    ]

    coll    = app.mongodb[EXCHANGES_OI_COLLECTION]
    results = await coll.aggregate(pipeline).to_list(length=100)

    grouped = {}
    for doc in results:
        doc["_id"] = str(doc["_id"])
        coin = doc.get("coin", "UNKNOWN")
        if coin not in grouped:
            grouped[coin] = []
        grouped[coin].append({
            "exchange":          doc.get("exchange"),
            "oi_usd":            doc.get("oi_usd"),
            "mark_px":           doc.get("mark_px"),
            "oi_30min_ago":      doc.get("oi_30min_ago"),
            "change_pct_30min":  doc.get("change_pct_30min"),
            "px_change_30min":   doc.get("px_change_30min"),
            "trend_label":       doc.get("trend_label"),
            "timestamp":         doc.get("timestamp"),
        })

    return grouped

class WatchlistItem(BaseModel):
    user_id: str
    wallet_address: str
    label: str = ""


@app.get("/api/watchlist/{user_id}")
async def get_watchlist(user_id: str):
    col = app.mongodb[WATCHLISTS_COLLECTION]
    cursor = col.find({"user_id": user_id}, {"_id": 0})
    items = [doc async for doc in cursor]
    return items


@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem):
    col = app.mongodb[WATCHLISTS_COLLECTION]
    existing = await col.find_one({"user_id": item.user_id, "wallet_address": item.wallet_address})
    if existing:
        raise HTTPException(status_code=409, detail="Already in watchlist")
    await col.insert_one(item.dict())
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
        {"$set": {
            "user_id":     data["user_id"],
            "telegram_id": data["telegram_id"],
        }},
        upsert=True
    )
    return {"message": "Telegram ID saved"}
