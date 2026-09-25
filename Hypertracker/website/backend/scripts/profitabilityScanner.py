import asyncio
import json
import os
from pathlib import Path
from datetime import datetime
# from motor.motor_asyncio import AsyncIOMotorClient
# from pymongo import UpdateOne, DeleteMany
from dotenv import load_dotenv
import httpx

from sqlite_db import get_async_connection, loads
from hyperliquid_client import WEIGHT_BUDGETS, WeightLimiter, parse_open_positions, post_info

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Schema definition ────────────────────────────────────────────────────────
REQUIRED_INACTIVE = {"wallet_address", "has_trading_activity", "account_value",
                     "withdrawable_balance", "user_role", "last_updated"}

REQUIRED_ACTIVE = REQUIRED_INACTIVE | {
    "total_pnl_usdc", "realized_pnl_usdc", "unrealized_pnl_usdc",
    "profit_percentage", "trade_count", "winning_trades", "losing_trades",
    "total_volume_usdc", "avg_trade_size_usdc", "win_rate_percentage",
    "max_drawdown_percentage", "open_positions_count", "open_positions",
    "is_likely_bot", "user_cross_rate", "user_add_rate", "fee_tier",
    "staking_discount", "is_vault_depositor", "historical_pnl",
    "historical_balance"
}

REQUIRED_BOT = {"wallet_address", "is_likely_bot", "has_trading_activity",
                "account_value", "total_volume_usdc", "user_role", "last_updated"}

FIELD_TYPES = {
    "wallet_address":           str,
    "has_trading_activity":     bool,
    "account_value":            (int, float),
    "withdrawable_balance":     (int, float),
    "total_pnl_usdc":           (int, float),
    "realized_pnl_usdc":        (int, float),
    "unrealized_pnl_usdc":      (int, float),
    "profit_percentage":        (int, float),
    "trade_count":              int,
    "winning_trades":           int,
    "losing_trades":            int,
    "total_volume_usdc":        (int, float),
    "avg_trade_size_usdc":      (int, float),
    "win_rate_percentage":      (int, float),
    "max_drawdown_percentage":  (int, float),
    "open_positions_count":     int,
    "open_positions":           list,
    "is_likely_bot":            bool,
    "user_cross_rate":          (int, float),
    "user_add_rate":            (int, float),
    "fee_tier":                 int,
    "staking_discount":         (int, float),
    "is_vault_depositor":       bool,
    "historical_pnl":           dict,
    "historical_balance":       dict,
    "user_role":                str,
    "last_updated":             datetime,
}


def _classify_document(doc: dict) -> str:
    """Return 'bot', 'active', 'inactive', or 'invalid'."""
    if doc.get("is_likely_bot") is True:
        return "bot"
    if doc.get("has_trading_activity") is True:
        return "active"
    if doc.get("has_trading_activity") is False:
        return "inactive"
    return "invalid"


def _is_valid_document(doc: dict) -> bool:
    """Return True only when the document satisfies the expected schema."""
    kind = _classify_document(doc)

    if kind == "bot":
        required = REQUIRED_BOT
    elif kind == "active":
        required = REQUIRED_ACTIVE
    elif kind == "inactive":
        required = REQUIRED_INACTIVE
    else:
        return False  # can't determine shape → treat as invalid

    # 1. All required keys must be present and not None
    for key in required:
        if key not in doc or doc[key] is None:
            return False

    # 2. Type-check every present field that we know about
    for key, expected_type in FIELD_TYPES.items():
        if key not in doc:
            continue
        if not isinstance(doc[key], expected_type):
            return False

    # 3. wallet_address must be a non-empty string
    if not doc.get("wallet_address", "").strip():
        return False

    return True


class ProfitabilityScanner:

    def __init__(self, mongo_uri, weight_per_min=None, concurrency=20):
        # self.client = AsyncIOMotorClient(mongo_uri)
        # self.db = self.client["hyperliquid"]
        self.mongo_uri = mongo_uri
        self.db = None  # aiosqlite connection, created lazily via _get_db()
        self._http = None
        # the WeightLimiter is what actually caps request rate, so this just needs to
        # be high enough to keep the httpx connection pool (below) saturated rather
        # than sitting idle waiting on a scarce semaphore slot.
        self._sem = asyncio.Semaphore(concurrency)
        # this process's fixed slice of the shared 1200/min Hyperliquid budget —
        # see hyperliquid_client.WEIGHT_BUDGETS for why it's not the full 1200.
        self._limiter = WeightLimiter(weight_per_min or WEIGHT_BUDGETS["profitability_scanner"])
        self._phase1_done = False
        self._cycles_since_phase1_check = 0
        self._indexes_created = False
        # running totals since this process started, for progress logging
        self._session_scanned = 0
        self._session_bots = 0
        self._session_failed = 0
        self._batch_count = 0

    async def _get_http(self):
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=10,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=20),
            )
        return self._http

    async def _get_db(self):
        if self.db is None:
            self.db = await get_async_connection()
        return self.db

    async def _get_existing_metrics(self, wallet_address):
        db = await self._get_db()
        cursor = await db.execute(
            "SELECT data FROM profitability_metrics WHERE wallet_address = ?", (wallet_address,)
        )
        row = await cursor.fetchone()
        return loads(row["data"]) if row else None

    # user_role/sub_accounts/is_vault_depositor almost never change once set, but userRole
    # alone costs 60 weight — by far the most expensive call this scanner makes, and roughly
    # half the weight of a full scan. Only re-fetch them when we don't have a recent answer.
    ROLE_REFRESH_SECONDS = 24 * 60 * 60

    @classmethod
    def _role_info_stale(cls, existing):
        if not existing:
            return True
        if not existing.get("user_role") or existing.get("user_role") == "unknown":
            return True
        checked_at = existing.get("role_checked_at")
        if not checked_at:
            return True
        try:
            checked = datetime.fromisoformat(checked_at)
        except (TypeError, ValueError):
            return True
        return (datetime.now() - checked).total_seconds() >= cls.ROLE_REFRESH_SECONDS

    async def _upsert_many(self, docs):
        """Upsert all docs in one executemany + one commit (one fsync per batch, not per wallet)."""
        if not docs:
            return
        db = await self._get_db()
        await db.executemany(self._UPSERT_SQL, [self._metrics_row(d) for d in docs])
        await db.commit()

    @staticmethod
    def _metrics_row(doc: dict):
        last_updated = doc.get("last_updated")
        if hasattr(last_updated, "isoformat"):
            last_updated = str(last_updated)
        return (doc.get("wallet_address"), doc.get("total_pnl_usdc"), doc.get("max_drawdown_percentage"),
                int(bool(doc.get("is_likely_bot"))) if doc.get("is_likely_bot") is not None else None,
                doc.get("trade_count"), doc.get("account_value"), doc.get("fee_tier"),
                doc.get("win_rate_percentage"),
                int(bool(doc.get("has_trading_activity"))) if doc.get("has_trading_activity") is not None else None,
                doc.get("open_positions_count"), doc.get("user_role"), last_updated,
                json.dumps(doc, default=str))

    _UPSERT_SQL = """INSERT INTO profitability_metrics
               (wallet_address, total_pnl_usdc, max_drawdown_percentage, is_likely_bot, trade_count,
                account_value, fee_tier, win_rate_percentage, has_trading_activity, open_positions_count,
                user_role, last_updated, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(wallet_address) DO UPDATE SET
                 total_pnl_usdc=excluded.total_pnl_usdc, max_drawdown_percentage=excluded.max_drawdown_percentage,
                 is_likely_bot=excluded.is_likely_bot, trade_count=excluded.trade_count,
                 account_value=excluded.account_value, fee_tier=excluded.fee_tier,
                 win_rate_percentage=excluded.win_rate_percentage, has_trading_activity=excluded.has_trading_activity,
                 open_positions_count=excluded.open_positions_count, user_role=excluded.user_role,
                 last_updated=excluded.last_updated, data=excluded.data"""

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
        if self.db is not None:
            await self.db.close()

    async def setup_indexes(self):
        if self._indexes_created:
            return
        # await self.db.profitability_metrics.create_index("wallet_address", unique=True)
        # await self.db.profitability_metrics.create_index([("total_pnl_usdc", -1)])
        # await self.db.profitability_metrics.create_index("has_trading_activity")
        # await self.db.profitability_metrics.create_index("account_value")
        # await self.db.profitability_metrics.create_index("win_rate_percentage")
        # await self.db.profitability_metrics.create_index("trade_count")
        # await self.db.profitability_metrics.create_index("is_likely_bot")
        # await self.db.profitability_metrics.create_index("user_role")
        # await self.db.profitability_metrics.create_index("fee_tier")
        # await self.db.profitability_metrics.create_index("open_positions_count")
        # await self.db.users.create_index("user", unique=True)
        # indexes/unique constraints are already declared in sqlite_db.SCHEMA_SQL — just ensure the connection exists.
        await self._get_db()
        self._indexes_created = True

    # ── NEW: purge malformed documents ───────────────────────────────────────
    async def purge_invalid_documents(self, batch_size: int = 500) -> int:
        """
        Stream through profitability_metrics in batches and delete any document
        that does not pass _is_valid_document(). Returns total deleted count.
        """
        db = await self._get_db()
        total_deleted = 0
        # cursor = self.db.profitability_metrics.find(
        #     {}, {"_id": 1, "wallet_address": 1, "has_trading_activity": 1,
        #          "is_likely_bot": 1, "total_pnl_usdc": 1, "realized_pnl_usdc": 1,
        #          "unrealized_pnl_usdc": 1, "profit_percentage": 1, "trade_count": 1,
        #          "winning_trades": 1, "losing_trades": 1, "total_volume_usdc": 1,
        #          "avg_trade_size_usdc": 1, "win_rate_percentage": 1,
        #          "max_drawdown_percentage": 1, "open_positions_count": 1,
        #          "open_positions": 1, "user_cross_rate": 1, "user_add_rate": 1,
        #          "fee_tier": 1, "staking_discount": 1, "is_vault_depositor": 1,
        #          "historical_pnl": 1, "historical_balance": 1, "account_value": 1,
        #          "withdrawable_balance": 1, "user_role": 1, "last_updated": 1}
        # )
        #
        # bad_ids = []
        # async for doc in cursor:
        #     if not _is_valid_document(doc):
        #         bad_ids.append(doc["_id"])
        #
        #     if len(bad_ids) >= batch_size:
        #         result = await self.db.profitability_metrics.delete_many(
        #             {"_id": {"$in": bad_ids}}
        #         )
        #         total_deleted += result.deleted_count
        #         print(f"{datetime.now().strftime('%H:%M:%S')} purged {result.deleted_count} invalid docs")
        #         bad_ids = []
        #
        # # flush remainder
        # if bad_ids:
        #     result = await self.db.profitability_metrics.delete_many(
        #         {"_id": {"$in": bad_ids}}
        #     )
        #     total_deleted += result.deleted_count
        #     print(f"{datetime.now().strftime('%H:%M:%S')} purged {result.deleted_count} invalid docs (final batch)")
        #
        # return total_deleted

        # keyset pagination (WHERE id > last_id) instead of OFFSET, so deleting
        # rows mid-stream never skips over the next page.
        bad_ids = []
        last_id = 0
        while True:
            cursor = await db.execute(
                "SELECT id, data FROM profitability_metrics WHERE id > ? ORDER BY id LIMIT ?",
                (last_id, batch_size),
            )
            rows = await cursor.fetchall()
            if not rows:
                break
            last_id = rows[-1]["id"]

            for row in rows:
                doc = loads(row["data"])
                # _is_valid_document expects a native datetime for last_updated (how Motor/BSON
                # deserialized it); the JSON blob round-trips it as an isoformat string, so convert
                # it back before validating rather than loosen the validator's original contract.
                lu = doc.get("last_updated")
                if isinstance(lu, str):
                    try:
                        doc["last_updated"] = datetime.fromisoformat(lu)
                    except ValueError:
                        pass
                if not _is_valid_document(doc):
                    bad_ids.append(row["id"])

            if len(bad_ids) >= batch_size:
                placeholders = ",".join("?" * len(bad_ids))
                await db.execute(f"DELETE FROM profitability_metrics WHERE id IN ({placeholders})", bad_ids)
                await db.commit()
                total_deleted += len(bad_ids)
                print(f"{datetime.now().strftime('%H:%M:%S')} purged {len(bad_ids)} invalid docs")
                bad_ids = []

        if bad_ids:
            placeholders = ",".join("?" * len(bad_ids))
            await db.execute(f"DELETE FROM profitability_metrics WHERE id IN ({placeholders})", bad_ids)
            await db.commit()
            total_deleted += len(bad_ids)
            print(f"{datetime.now().strftime('%H:%M:%S')} purged {len(bad_ids)} invalid docs (final batch)")

        return total_deleted

    async def scan_wallets(self, batch_size=100):
        db = await self._get_db()
        self._cycles_since_phase1_check += 1
        skip_phase1 = self._phase1_done and self._cycles_since_phase1_check < 10

        if not skip_phase1:
            self._cycles_since_phase1_check = 0
            # pipeline = [
            #     {"$match": {"user": {"$exists": True}}},
            #     {"$lookup": {
            #         "from": "profitability_metrics",
            #         "localField": "user",
            #         "foreignField": "wallet_address",
            #         "as": "metrics"
            #     }},
            #     {"$match": {"metrics": {"$size": 0}}},
            #     {"$project": {"user": 1, "_id": 0}},
            #     {"$limit": batch_size}
            # ]
            # never_scanned = [doc["user"] async for doc in self.db.users.aggregate(pipeline)]
            cursor = await db.execute(
                "SELECT users.user FROM users "
                "LEFT JOIN profitability_metrics ON profitability_metrics.wallet_address = users.user "
                "WHERE profitability_metrics.wallet_address IS NULL "
                "LIMIT ?",
                (batch_size,),
            )
            never_scanned = [row["user"] for row in await cursor.fetchall()]
            if never_scanned:
                self._phase1_done = False
                return never_scanned, "phase1"
            else:
                self._phase1_done = True

        # stalest = await self.db.profitability_metrics.find(
        #     {}, {"wallet_address": 1, "last_updated": 1, "_id": 0}
        # ).sort("last_updated", 1).limit(batch_size).to_list(batch_size)
        cursor = await db.execute(
            "SELECT wallet_address FROM profitability_metrics ORDER BY last_updated ASC LIMIT ?",
            (batch_size,),
        )
        stalest = await cursor.fetchall()

        if not stalest:
            return [], None

        return [row["wallet_address"] for row in stalest], "phase2"

    async def _api_post(self, payload, retries=5, timeout=10):
        http = await self._get_http()
        return await post_info(http, self._limiter, payload, retries=retries, timeout=timeout)

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
        fills_task = None
        try:
            existing = await self._get_existing_metrics(wallet_address)
            refresh_role = self._role_info_stale(existing)

            # Pacing is handled by the shared weight limiter, so independent calls can overlap.
            state, portfolio = await asyncio.gather(
                self._api_post({"type": "clearinghouseState", "user": wallet_address}),
                self._api_post({"type": "portfolio", "user": wallet_address}),
            )

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
            is_inactive   = total_volume == 0 and realized_pnl == 0

            # Inactive wallets never use fee data or fills, so don't spend weight on them;
            # for active ones the fills download overlaps the metadata calls. userRole/
            # subAccounts/userVaultEquities are skipped entirely once we have a recent
            # cached answer — userRole alone is 60 weight, by far the priciest call here.
            tasks = {}
            if refresh_role:
                tasks["role"]  = self._api_post({"type": "userRole", "user": wallet_address})
                tasks["sub"]   = self._api_post({"type": "subAccounts", "user": wallet_address})
                tasks["vault"] = self._api_post({"type": "userVaultEquities", "user": wallet_address})
            if not is_inactive:
                tasks["fees"] = self._api_post({"type": "userFees", "user": wallet_address})
                fills_task = asyncio.ensure_future(self._fetch_fills(wallet_address))

            results = dict(zip(tasks.keys(), await asyncio.gather(*tasks.values()))) if tasks else {}
            role_data  = results.get("role")
            sub_data   = results.get("sub")
            vault_data = results.get("vault")
            fees_data  = results.get("fees")

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

            if refresh_role:
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
                role_checked_at = datetime.now().isoformat()
            else:
                cached              = existing or {}
                user_role           = cached.get("user_role", "unknown")
                master_wallet       = cached.get("master_wallet")
                sub_accounts        = cached.get("sub_accounts", [])
                is_vault_depositor  = cached.get("is_vault_depositor", False)
                role_checked_at     = cached.get("role_checked_at") or datetime.now().isoformat()

            if is_inactive:
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
                    "role_checked_at": role_checked_at,
                    "last_updated": datetime.now()
                }

        except Exception:
            if fills_task is not None:
                fills_task.cancel()
            return None

        fills, is_bot_by_fills = await fills_task

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
            bot_doc = {
                "wallet_address": wallet_address,
                "is_likely_bot": True,
                "has_trading_activity": True,
                "account_value": round(account_value, 2),
                "total_volume_usdc": round(total_volume, 2),
                "user_role": user_role,
                "role_checked_at": role_checked_at,
                "last_updated": datetime.now()
            }
            # await self.db.profitability_metrics.update_one(
            #     {"wallet_address": wallet_address},
            #     {"$set": bot_doc},
            #     upsert=True
            # )
            return bot_doc

        open_positions = parse_open_positions(state.get("assetPositions", []))

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
            "role_checked_at": role_checked_at,
            "last_updated": datetime.now()
        }

    async def _scan_one(self, wallet):
        async with self._sem:
            return await self.calculate_profitability(wallet)

    async def scan_batch(self, batch_size=100):
        wallets, phase = await self.scan_wallets(batch_size)
        if not wallets:
            return 0

        print(f"{datetime.now().strftime('%H:%M:%S')} scanning {len(wallets)} wallets [{phase}]...")

        results = await asyncio.gather(
            *(self._scan_one(w) for w in wallets),
            return_exceptions=True
        )

        docs_to_upsert = []
        processed = failed = bots = 0

        for wallet, metrics in zip(wallets, results):
            if isinstance(metrics, Exception) or metrics is None:
                print(f"{datetime.now().strftime('%H:%M:%S')} failed {wallet}")
                failed += 1
                continue
            if metrics.get("is_likely_bot") and metrics.get("has_trading_activity"):
                print(f"{datetime.now().strftime('%H:%M:%S')} bot found {wallet}")
                bots += 1
            else:
                print(f"{datetime.now().strftime('%H:%M:%S')} processed {wallet}")
            # ops.append(UpdateOne({"wallet_address": wallet}, {"$set": metrics}, upsert=True))
            docs_to_upsert.append(metrics)
            processed += 1

        # if ops:
        #     await self.db.profitability_metrics.bulk_write(ops, ordered=False)
        await self._upsert_many(docs_to_upsert)

        self._batch_count += 1
        self._session_scanned += processed
        self._session_bots += bots
        self._session_failed += failed
        print(f"{datetime.now().strftime('%H:%M:%S')} --- batch #{self._batch_count} [{phase}] "
              f"done: {processed}/{len(wallets)} ok, {bots} bots, {failed} failed | "
              f"session totals: scanned={self._session_scanned} bots={self._session_bots} failed={self._session_failed} ---")

        return processed

    async def run_continuous(self):
        await self.setup_indexes()
        # ── purge on startup, then every 50 cycles ───────────────────────────
        purge_cycle = 0
        PURGE_EVERY  = 50

        try:
            while True:
                try:
                    if purge_cycle % PURGE_EVERY == 0:
                        deleted = await self.purge_invalid_documents()
                        if deleted:
                            print(f"{datetime.now().strftime('%H:%M:%S')} purge complete — {deleted} invalid docs removed")

                    processed = await self.scan_batch(batch_size=100)
                    purge_cycle += 1
                    await asyncio.sleep(600 if processed == 0 else 1)
                except KeyboardInterrupt:
                    break
                except Exception:
                    await asyncio.sleep(300)
        finally:
            await self.close()


async def main():
    scanner = ProfitabilityScanner(os.getenv("MONGO_URI"))
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())