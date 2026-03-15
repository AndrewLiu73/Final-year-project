import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

load_dotenv(Path(__file__).resolve().parent / ".env")

MONGO_URI           = os.getenv("MONGO_URI")
TELEGRAM_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.mongodb_client = AsyncIOMotorClient(MONGO_URI)
    app.mongodb        = app.mongodb_client["hyperliquid"]
    app.http_client    = httpx.AsyncClient(timeout=10)
    yield
    await app.http_client.aclose()
    app.mongodb_client.close()

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:3000"],
    allow_methods=["*"], allow_headers=["*"])


@app.get("/api/millionaires", response_model=List[dict])
async def get_millionaires():
    return [doc async for doc in app.mongodb["millionaires"].find({}, {"_id": 0, "wallet": 1, "balance": 1})]


@app.get("/api/bias-summaries")
async def get_bias_summaries():
    return [doc async for doc in app.mongodb["bias_summaries"].find({}, {"_id": 0})]


@app.get("/api/users/profitable")
async def get_profitable_traders(
    page: int = Query(1, ge=1), page_size: int = Query(100, ge=10, le=200),
    sort_by: str = Query("pnl"), sort_direction: str = Query("desc"),
    min_winrate: float = Query(None), max_drawdown: float = Query(None),
    min_balance: float = Query(None), max_balance: float = Query(None),
    activity_filter: str = Query("all"), positions_filter: str = Query("all"),
    is_bot: str = Query(None), search: str = Query(None),
) -> Dict:
    coll, query = app.mongodb["profitability_metrics"], {}

    if min_winrate  is not None: query["win_rate_percentage"]    = {"$gte": min_winrate}
    if max_drawdown is not None: query["max_drawdown_percentage"] = {"$lte": max_drawdown}
    if min_balance  is not None: query.setdefault("account_value", {})["$gte"] = min_balance
    if max_balance  is not None: query.setdefault("account_value", {})["$lte"] = max_balance
    if activity_filter  == "active":    query["total_volume_usdc"]    = {"$gt": 0}
    elif activity_filter == "inactive": query["total_volume_usdc"]    = {"$lte": 0}
    if positions_filter == "yes":       query["open_positions_count"] = {"$gt": 0}
    elif positions_filter == "no":      query["open_positions_count"] = 0
    if is_bot == "true":   query["is_likely_bot"] = True
    elif is_bot == "false": query["is_likely_bot"] = {"$ne": True}
    if search: query["wallet_address"] = {"$regex": search, "$options": "i"}

    field = {"pnl": "total_pnl_usdc", "balance": "account_value", "winrate": "win_rate_percentage",
             "drawdown": "max_drawdown_percentage", "openTrades": "open_positions_count"}.get(sort_by, "total_pnl_usdc")
    direction   = -1 if sort_direction == "desc" else 1
    total_count = await coll.count_documents(query)
    skip        = (page - 1) * page_size
    docs        = await coll.find(query, {"_id": 0}).sort(field, direction).skip(skip).limit(page_size).to_list(page_size)

    traders = []
    for doc in docs:
        pnl, vol = doc.get("total_pnl_usdc", 0), doc.get("total_volume_usdc", 0)
        traders.append({
            "wallet": doc.get("wallet_address"),
            "currentBalance": doc.get("account_value", 0),
            "withdrawableBalance": doc.get("withdrawable_balance", 0),
            "gainDollar": pnl, "gainPercent": round(pnl / vol * 100, 2) if vol > 0 else 0,
            "isProfitable": pnl > 0, "winrate": doc.get("win_rate_percentage", 0),
            "maxDrawdown": doc.get("max_drawdown_percentage", 0), "tradeCount": doc.get("trade_count", 0),
            "winningTrades": doc.get("winning_trades", 0), "losingTrades": doc.get("losing_trades", 0),
            "openPositionsCount": doc.get("open_positions_count", 0), "openPositions": doc.get("open_positions", []),
            "totalVolume": vol, "avgTradeSize": doc.get("avg_trade_size_usdc", 0),
            "realizedPnl": doc.get("realized_pnl_usdc", 0), "unrealizedPnl": doc.get("unrealized_pnl_usdc", 0),
            "userRole": doc.get("user_role", "unknown"), "masterWallet": doc.get("master_wallet"),
            "subAccounts": doc.get("sub_accounts", []), "subAccountCount": doc.get("sub_account_count", 0),
            "isLikelyBot": doc.get("is_likely_bot", False), "isVaultDepositor": doc.get("is_vault_depositor", False),
            "feeTier": doc.get("fee_tier", 0), "userCrossRate": doc.get("user_cross_rate", 0),
            "userAddRate": doc.get("user_add_rate", 0), "stakingDiscount": doc.get("staking_discount", 0),
            "historicalPnl": doc.get("historical_pnl", {}), "historicalBalance": doc.get("historical_balance", {}),
            "lastUpdated": str(doc.get("last_updated", "")),
        })

    return {"data": traders, "pagination": {"total_count": total_count, "page": page,
            "page_size": page_size, "has_more": (skip + len(traders)) < total_count}}


@app.get("/api/users/trader/{wallet_address}")
async def get_trader_details(wallet_address: str) -> Dict:
    trader = await app.mongodb["profitability_metrics"].find_one({"wallet_address": wallet_address}, {"_id": 0})
    if not trader: raise HTTPException(404, "Trader not found")
    pnl, trades, wins, losses = (trader.get(k, 0) for k in ("total_pnl_usdc", "trade_count", "winning_trades", "losing_trades"))
    trader |= {"total_pnl": pnl, "realized_pnl": trader.get("realized_pnl_usdc", 0),
               "unrealized_pnl": trader.get("unrealized_pnl_usdc", 0),
               "win_loss_ratio": round(wins / losses, 2) if losses else float(wins),
               "avg_profit_per_trade": round(pnl / trades, 2) if trades else 0, "data_source": "cached"}
    return trader


@app.get("/api/users/trader/{wallet_address}/live")
async def get_trader_live_data(wallet_address: str) -> Dict:
    client = app.http_client
    state_r, portfolio_r, spot_r, mids_r = await asyncio.gather(
        client.post(HYPERLIQUID_API_URL, json={"type": "clearinghouseState",     "user": wallet_address}),
        client.post(HYPERLIQUID_API_URL, json={"type": "portfolio",              "user": wallet_address}),
        client.post(HYPERLIQUID_API_URL, json={"type": "spotClearinghouseState", "user": wallet_address}),
        client.post(HYPERLIQUID_API_URL, json={"type": "allMids"}),
    )
    if state_r.status_code != 200: raise HTTPException(502, "Failed to fetch live data from Hyperliquid")

    state    = state_r.json()
    ms       = state.get("marginSummary", {})
    perp_val = float(ms.get("accountValue", 0))
    withdraw = float(state.get("withdrawable", 0))

    spot_val, mids = 0.0, mids_r.json() if mids_r.status_code == 200 else {}
    if spot_r.status_code == 200:
        for b in spot_r.json().get("balances", []):
            coin, total = b.get("coin", ""), float(b.get("total", 0))
            spot_val += total if coin == "USDC" else total * float(mids[coin]) if coin in mids else 0

    portfolio = portfolio_r.json() if portfolio_r.status_code == 200 else []
    all_time  = next((p[1] for p in portfolio if p[0] == "allTime"), None)
    pnl_hist  = all_time.get("pnlHistory", []) if all_time else []
    realized  = float(pnl_hist[-1][1]) if pnl_hist else 0.0
    total_vol = float(all_time.get("vlm", 0)) if all_time else 0.0

    unrealized, open_positions = 0.0, []
    for pos in state.get("assetPositions", []):
        pd   = pos.get("position", {})
        size = float(pd.get("szi", 0))
        if not size: continue
        upnl = float(pd.get("unrealizedPnl", 0))
        unrealized += upnl
        open_positions.append({"asset": pd.get("coin", "UNKNOWN"), "direction": "LONG" if size > 0 else "SHORT",
                                "size": abs(size), "entry_price": float(pd.get("entryPx", 0)), "unrealized_pnl": round(upnl, 2)})

    total_pnl, total_val = realized + unrealized, perp_val + spot_val
    initial_bal = total_val - total_pnl if total_pnl else total_val
    return {
        "wallet_address": wallet_address, "account_value": round(total_val, 2),
        "perp_account_value": round(perp_val, 2), "spot_account_value": round(spot_val, 2),
        "withdrawable_balance": round(withdraw, 2), "total_pnl": round(total_pnl, 2),
        "realized_pnl": round(realized, 2), "unrealized_pnl": round(unrealized, 2),
        "profit_percentage": round(total_pnl / initial_bal * 100, 2) if initial_bal else 0,
        "total_volume_usdc": round(total_vol, 2), "open_positions": open_positions,
        "open_positions_count": len(open_positions), "last_updated": datetime.now().isoformat(), "data_source": "live"
    }


@app.get("/api/exchange-oi")
async def get_exchange_oi():
    pipeline = [{"$sort": {"timestamp": -1}},
                {"$group": {"_id": {"coin": "$coin", "exchange": "$exchange"}, "doc": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$doc"}}]
    results, grouped = await app.mongodb["exchange_oi"].aggregate(pipeline).to_list(100), {}
    for doc in results:
        grouped.setdefault(doc.get("coin", "UNKNOWN"), []).append(
            {k: doc.get(k) for k in ("exchange", "oi_usd", "mark_px", "oi_30min_ago", "change_pct_30min", "px_change_30min", "trend_label", "timestamp")})
    return grouped


@app.get("/api/large-positions")
async def get_large_positions(
    min_notional_usd: Optional[float] = Query(10000, ge=0), asset: Optional[str] = Query(None),
    direction: Optional[str] = Query(None), sort_by: str = Query("notional_usd"),
    sort_direction: str = Query("desc"), page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
):
    coll, query = app.mongodb["open_positions"], {}
    if min_notional_usd: query["notional_usd"] = {"$gte": min_notional_usd}
    if asset:            query["asset"]         = asset.upper()
    if direction:        query["direction"]     = direction.upper()

    field     = {"notional_usd": "notional_usd", "unrealized_pnl": "unrealized_pnl",
                 "account_value": "account_value", "size": "size"}.get(sort_by, "notional_usd")
    mongo_dir   = -1 if sort_direction == "desc" else 1
    total_count = await coll.count_documents(query)
    unique_wallets = len(await coll.distinct("wallet_address", query))
    skip    = (page - 1) * page_size
    results = await coll.find(query, {"_id": 0}).sort(field, mongo_dir).skip(skip).limit(page_size).to_list(page_size)

    for r in results:
        if r.get("last_updated") and hasattr(r["last_updated"], "isoformat"):
            r["last_updated"] = r["last_updated"].isoformat()

    return {"data": results, "pagination": {"total_count": total_count, "unique_wallets": unique_wallets,
            "page": page, "page_size": page_size, "has_more": (skip + len(results)) < total_count}}


@app.get("/api/asset-concentration")
async def get_asset_concentration():
    results = await app.mongodb["asset_concentration"].find({}, {"_id": 0}).sort("total_notional", -1).to_list(200)
    for r in results:
        if r.get("last_updated") and hasattr(r["last_updated"], "isoformat"):
            r["last_updated"] = r["last_updated"].isoformat()
    return results


class WatchlistItem(BaseModel):
    user_id: str
    wallet_address: str
    label: str = ""

@app.get("/api/watchlist/{user_id}")
async def get_watchlist(user_id: str):
    return [doc async for doc in app.mongodb["watchlists"].find({"user_id": user_id}, {"_id": 0})]

@app.post("/api/watchlist")
async def add_to_watchlist(item: WatchlistItem):
    if await app.mongodb["watchlists"].find_one({"user_id": item.user_id, "wallet_address": item.wallet_address}):
        raise HTTPException(409, "Already in watchlist")
    await app.mongodb["watchlists"].insert_one(item.model_dump())
    return {"message": "Added to watchlist"}

@app.delete("/api/watchlist/{user_id}/{wallet_address}")
async def remove_from_watchlist(user_id: str, wallet_address: str):
    result = await app.mongodb["watchlists"].delete_one({"user_id": user_id, "wallet_address": wallet_address})
    if not result.deleted_count: raise HTTPException(404, "Not found in watchlist")
    return {"message": "Removed from watchlist"}

@app.post("/api/users/telegram")
async def save_telegram_id(data: dict):
    await app.mongodb["users"].update_one({"user_id": data["user_id"]},
        {"$set": {"user_id": data["user_id"], "telegram_id": data["telegram_id"]}}, upsert=True)
    return {"message": "Telegram ID saved"}
