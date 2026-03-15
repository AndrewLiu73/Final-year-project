import asyncio
import os
import time
from pathlib import Path
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from dotenv import load_dotenv
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class ProfitabilityScanner:

    def __init__(self, mongo_uri, rpm=200):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client["hyperliquid"]
        self.delay = 60.0 / rpm
        self._http = None
        self._sem = asyncio.Semaphore(5)
        self._active_slots = {}
        self._slot_lock = None
        self._last_ratchet = 0
        self._phase1_done = False
        self._cycles_since_phase1_check = 0
        self._indexes_created = False

    async def _get_http(self):
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def setup_indexes(self):
        if self._indexes_created:
            return
        await self.db.profitability_metrics.create_index("wallet_address", unique=True)
        await self.db.profitability_metrics.create_index([("total_pnl_usdc", -1)])
        await self.db.profitability_metrics.create_index("has_trading_activity")
        await self.db.profitability_metrics.create_index("account_value")
        await self.db.profitability_metrics.create_index("win_rate_percentage")
        await self.db.profitability_metrics.create_index("trade_count")
        await self.db.profitability_metrics.create_index("is_likely_bot")
        await self.db.profitability_metrics.create_index("user_role")
        await self.db.profitability_metrics.create_index("fee_tier")
        await self.db.profitability_metrics.create_index("open_positions_count")
        await self.db.users.create_index("user", unique=True)
        self._indexes_created = True

    async def scan_wallets(self, batch_size=100):
        self._cycles_since_phase1_check += 1
        skip_phase1 = self._phase1_done and self._cycles_since_phase1_check < 10

        if not skip_phase1:
            self._cycles_since_phase1_check = 0
            pipeline = [
                {"$match": {"user": {"$exists": True}}},
                {"$lookup": {
                    "from": "profitability_metrics",
                    "localField": "user",
                    "foreignField": "wallet_address",
                    "as": "metrics"
                }},
                {"$match": {"metrics": {"$size": 0}}},
                {"$project": {"user": 1, "_id": 0}},
                {"$limit": batch_size}
            ]
            never_scanned = [doc["user"] async for doc in self.db.users.aggregate(pipeline)]
            if never_scanned:
                self._phase1_done = False
                return never_scanned, "phase1"
            else:
                self._phase1_done = True

        stalest = await self.db.profitability_metrics.find(
            {}, {"wallet_address": 1, "last_updated": 1, "_id": 0}
        ).sort("last_updated", 1).limit(batch_size).to_list(batch_size)

        if not stalest:
            return [], None

        return [doc["wallet_address"] for doc in stalest], "phase2"

    async def _api_post(self, payload, retries=5, timeout=10):
        http = await self._get_http()
        for attempt in range(retries):
            try:
                resp = await http.post(
                    "https://api.hyperliquid.xyz/info",
                    json=payload,
                    timeout=timeout
                )
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    await asyncio.sleep(5 * (2 ** attempt))
                    now = time.monotonic()
                    if now - self._last_ratchet > 5:
                        self.delay = min(self.delay * 1.5, 5.0)
                        self._last_ratchet = now
                    continue
                if resp.status_code == 422:
                    return None
            except (httpx.TimeoutException, asyncio.TimeoutError):
                await asyncio.sleep(2 * (attempt + 1))
        return None

    async def _fetch_fills(self, wallet_address, max_fills=10000):
        try:
            first_page = await self._api_post(
                {"type": "userFills", "user": wallet_address}, timeout=12
            ) or []

            if len(first_page) >= 2000:
                ts_min = min(int(f["time"]) for f in first_page)
                ts_max = max(int(f["time"]) for f in first_page)
                days = max((ts_max - ts_min) / 86400000, 1)
                if (len(first_page) / days) > 100 and days < 7:
                    return first_page, True

            all_fills = list(first_page)
            page = first_page

            while len(page) >= 2000 and len(all_fills) < max_fills:
                await asyncio.sleep(self.delay)
                oldest = min(int(f["time"]) for f in page)
                page = await self._api_post({
                    "type": "userFills",
                    "user": wallet_address,
                    "endTime": oldest - 1
                }, timeout=12) or []
                if not page:
                    break
                all_fills.extend(page)

            return all_fills, False
        except Exception:
            return [], False

    def _calculate_drawdown(self, fills):
        if not fills:
            return 0.0
        running, peak, worst_dd = 0, 0, 0
        for f in sorted(fills, key=lambda x: x.get("time", 0)):
            running += float(f.get("closedPnl", 0))
            if running > peak:
                peak = running
            if peak > 0:
                dd = ((peak - running) / peak) * 100
                if dd > worst_dd:
                    worst_dd = dd
        return worst_dd

    def _get_fee_tier(self, fee_schedule, user_cross_rate):
        try:
            tiers = fee_schedule.get("tiers", {}).get("vip", [])
            base = float(fee_schedule.get("cross", 0.00045))
            if float(user_cross_rate) >= base:
                return 0
            for i, tier in enumerate(tiers):
                if float(user_cross_rate) >= float(tier.get("cross", 0)):
                    return i + 1
            return len(tiers)
        except Exception:
            return 0

    async def calculate_profitability(self, wallet_address):
        try:
            state     = await self._api_post({"type": "clearinghouseState", "user": wallet_address})
            await asyncio.sleep(self.delay)
            portfolio = await self._api_post({"type": "portfolio", "user": wallet_address})
            await asyncio.sleep(self.delay)
            fees_data = await self._api_post({"type": "userFees", "user": wallet_address})
            await asyncio.sleep(self.delay)
            role_data = await self._api_post({"type": "userRole", "user": wallet_address})
            await asyncio.sleep(self.delay)
            sub_data  = await self._api_post({"type": "subAccounts", "user": wallet_address})
            await asyncio.sleep(self.delay)
            vault_data = await self._api_post({"type": "userVaultEquities", "user": wallet_address})
            await asyncio.sleep(self.delay)

            if not state or not portfolio:
                return None

            margin        = state.get("marginSummary", {})
            account_value = float(margin.get("accountValue", 0))
            withdrawable  = float(state.get("withdrawable", 0))

            unrealized_pnl = sum(
                float((pos.get("position") or {}).get("unrealizedPnl", 0))
                for pos in state.get("assetPositions", [])
                if isinstance(pos.get("position"), dict)
            )

            all_time    = next((p[1] for p in portfolio if p[0] == "allTime"), None)
            pnl_history = all_time.get("pnlHistory", []) if all_time else []
            realized_pnl  = float(pnl_history[-1][1]) if pnl_history else 0.0
            total_volume  = float(all_time.get("vlm", 0)) if all_time else 0.0

            historical_pnl     = {"day": [], "week": [], "month": [], "allTime": []}
            historical_balance = {"day": [], "week": [], "month": [], "allTime": []}

            for period_data in portfolio:
                name = period_data[0]
                if name not in historical_pnl or not isinstance(period_data[1], dict):
                    continue
                historical_pnl[name] = [
                    {"timestamp": int(pt[0]), "pnl": float(pt[1])}
                    for pt in period_data[1].get("pnlHistory", [])
                ]
                historical_balance[name] = [
                    {"timestamp": int(pt[0]), "balance": float(pt[1])}
                    for pt in period_data[1].get("accountValueHistory", [])
                ]

            user_cross_rate  = 0.0
            user_add_rate    = 0.0
            fee_tier         = 0
            staking_discount = 0.0

            if fees_data:
                user_cross_rate = float(fees_data.get("userCrossRate", 0))
                user_add_rate   = float(fees_data.get("userAddRate", 0))
                fee_tier        = self._get_fee_tier(fees_data.get("feeSchedule", {}), user_cross_rate)
                staking_raw     = fees_data.get("activeStakingDiscount")
                if isinstance(staking_raw, dict):
                    staking_discount = float(staking_raw.get("discount", 0))

            user_role     = "unknown"
            master_wallet = None
            if role_data:
                user_role = role_data.get("role", "unknown")
                rd = role_data.get("data") or {}
                if user_role == "subAccount":
                    master_wallet = rd.get("master")

            sub_accounts = [
                s.get("subAccountAddress") for s in (sub_data or [])
                if s.get("subAccountAddress")
            ]

            is_vault_depositor = bool(vault_data)

            if total_volume == 0 and realized_pnl == 0:
                return {
                    "wallet_address": wallet_address,
                    "has_trading_activity": False,
                    "account_value": round(account_value, 2),
                    "withdrawable_balance": round(withdrawable, 2),
                    "user_role": user_role,
                    "master_wallet": master_wallet,
                    "sub_account_count": len(sub_accounts),
                    "sub_accounts": sub_accounts,
                    "is_likely_bot": False,
                    "is_vault_depositor": is_vault_depositor,
                    "last_updated": datetime.now()
                }

        except Exception:
            return None

        fills, is_bot_by_fills = await self._fetch_fills(wallet_address)

        closing_fills = [f for f in fills if float(f.get("closedPnl", 0)) != 0]
        total_trades  = len(closing_fills)

        if fills:
            first_trade    = min(int(f["time"]) for f in fills)
            last_trade     = max(int(f["time"]) for f in fills)
            days_active    = max((last_trade - first_trade) / 86400000, 1)
            trades_per_day = total_trades / days_active
        else:
            trades_per_day = 0

        wins     = sum(1 for f in closing_fills if float(f.get("closedPnl", 0)) > 0)
        losses   = sum(1 for f in closing_fills if float(f.get("closedPnl", 0)) < 0)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        is_likely_bot = sum([
            is_bot_by_fills,
            user_cross_rate == 0.0,
            trades_per_day > 100,
            total_trades > 50000,
        ]) >= 2

        if is_likely_bot:
            await self.db.profitability_metrics.update_one(
                {"wallet_address": wallet_address},
                {"$set": {
                    "wallet_address": wallet_address,
                    "is_likely_bot": True,
                    "has_trading_activity": True,
                    "account_value": round(account_value, 2),
                    "total_volume_usdc": round(total_volume, 2),
                    "user_role": user_role,
                    "last_updated": datetime.now()
                }},
                upsert=True
            )
            return "bot"

        open_positions = []
        for pos in state.get("assetPositions", []):
            pd = pos.get("position") or {}
            try:
                size = float(pd.get("szi", 0) or 0)
            except (ValueError, TypeError):
                size = 0.0
            if size == 0:
                continue
            open_positions.append({
                "asset": pd.get("coin", "UNKNOWN"),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pd.get("entryPx") or 0),
                "unrealized_pnl": round(float(pd.get("unrealizedPnl") or 0), 2)
            })

        total_pnl  = realized_pnl + unrealized_pnl
        profit_pct = round((total_pnl / total_volume * 100), 2) if total_volume > 0 else 0

        return {
            "wallet_address": wallet_address,
            "has_trading_activity": True,
            "account_value": round(account_value, 2),
            "withdrawable_balance": round(withdrawable, 2),
            "total_pnl_usdc": round(total_pnl, 2),
            "realized_pnl_usdc": round(realized_pnl, 2),
            "unrealized_pnl_usdc": round(unrealized_pnl, 2),
            "profit_percentage": profit_pct,
            "trade_count": total_trades,
            "historical_pnl": historical_pnl,
            "historical_balance": historical_balance,
            "winning_trades": wins,
            "losing_trades": losses,
            "total_volume_usdc": round(total_volume, 2),
            "avg_trade_size_usdc": round(total_volume / total_trades, 2) if total_trades > 0 else 0,
            "win_rate_percentage": round(win_rate, 1),
            "max_drawdown_percentage": round(self._calculate_drawdown(fills), 2),
            "open_positions_count": len(open_positions),
            "open_positions": open_positions,
            "user_role": user_role,
            "master_wallet": master_wallet,
            "sub_account_count": len(sub_accounts),
            "sub_accounts": sub_accounts,
            "is_likely_bot": False,
            "user_cross_rate": user_cross_rate,
            "user_add_rate": user_add_rate,
            "fee_tier": fee_tier,
            "staking_discount": staking_discount,
            "is_vault_depositor": is_vault_depositor,
            "last_updated": datetime.now()
        }

    async def _scan_one(self, wallet):
        async with self._sem:
            if self._slot_lock is None:
                self._slot_lock = asyncio.Lock()
            async with self._slot_lock:
                used = set(self._active_slots.keys())
                slot = next(s for s in range(1, 6) if s not in used)
                self._active_slots[slot] = wallet
            try:
                await asyncio.sleep((slot - 1) * 1.0)
                return await self.calculate_profitability(wallet)
            finally:
                async with self._slot_lock:
                    self._active_slots.pop(slot, None)

    async def scan_batch(self, batch_size=100):
        wallets, phase = await self.scan_wallets(batch_size)
        if not wallets:
            return 0

        results = await asyncio.gather(
            *(self._scan_one(w) for w in wallets),
            return_exceptions=True
        )

        ops = []
        processed = 0

        for wallet, metrics in zip(wallets, results):
            if isinstance(metrics, Exception) or metrics is None:
                continue
            if metrics == "bot":
                processed += 1
            else:
                ops.append(UpdateOne({"wallet_address": wallet}, {"$set": metrics}, upsert=True))
                processed += 1

        if ops:
            await self.db.profitability_metrics.bulk_write(ops, ordered=False)

        return processed

    async def run_continuous(self):
        await self.setup_indexes()
        try:
            while True:
                try:
                    processed = await self.scan_batch(batch_size=100)
                    await asyncio.sleep(600 if processed == 0 else 10)
                except KeyboardInterrupt:
                    break
                except Exception:
                    await asyncio.sleep(300)
        finally:
            await self.close()


async def main():
    scanner = ProfitabilityScanner(os.getenv("MONGO_URI"), rpm=200)
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
