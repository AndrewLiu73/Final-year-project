# profitability scanner - scans wallets and calculates their pnl etc
# runs continuously on the CS server

import asyncio
import os
import logging
import time
from pathlib import Path
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from dotenv import load_dotenv
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log")

# using logging instead of print() so I can control verbosity with log levels
# and get timestamps automatically without manually formatting them everywhere
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scanner")

# httpx logs every single HTTP request at INFO level which floods the terminal.
# bump it to WARNING so we only see actual problems from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class ProfitabilityScanner:

    def __init__(self, mongo_uri, rpm=200):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client['hyperliquid']
        self.delay = 60.0 / rpm

        # using httpx.AsyncClient instead of the requests library because requests
        # blocks the entire event loop on every call. with httpx the scanner can
        # actually do other work while waiting for the API to respond, which is
        # the whole point of making this async in the first place
        self._http = None
        # dropped semaphore from 10 to 6 after noticing that 10 was too aggressive
        # all 10 fired clearinghouseState at the exact same millisecond on startup
        # and every single one got 429'd, a staggered start avoids that
        self._sem = asyncio.Semaphore(6)

        # maps slot number (1-6) to the wallet address currently using it.
        # lets us print which slot is doing what so you can see the concurrency
        # in real time instead of just a wall of wallet addresses
        self._active_slots = {}
        self._slot_lock = None  # lazy init, asyncio.Lock needs an event loop

        # tracks when we last bumped the delay. when 5 wallets all get 429'd in
        # the same second, we only want to ratchet self.delay ONCE, not 5 times.
        # without this it went 0.3 → 0.45 → 0.67 → 1.01 → 1.52 in one burst
        self._last_ratchet = 0

        # once phase 1 finishes (all wallets scanned at least once), don't
        # need to run the expensive $lookup every single cycle. this counter
        # tracks how many cycles since we last checked for new unscanned wallets.
        # re-checks every 10 cycles (~2 hours) in case new wallets were added
        self._phase1_done = False
        self._cycles_since_phase1_check = 0

        # indexes get set up in run_continuous() since motor needs an event loop
        self._indexes_created = False

    async def _get_http(self):
        """lazy init so we don't create the client until we're inside an event loop"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def setup_indexes(self):
        if self._indexes_created:
            return
        logger.info("setting up indexes")

        # these indexes match the sort/filter fields the frontend actually queries on.
        # without them mongo does a full collection scan on every /api/users/profitable call
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
        logger.info("indexes done\n")

    async def get_wallets_to_scan(self, batch_size=100):
        """
        Two-phase wallet selection:

        Phase 1 — never-scanned wallets first. Uses a $lookup to find users
        that don't have a matching document in profitability_metrics at all.
        The old approach grabbed 500 users and filtered client-side, which
        missed the 6k unscanned wallets when they weren't in the first 500.

        Phase 2 — once every wallet has been scanned at least once, rescan
        the stalest ones (oldest last_updated). Always refreshing the most
        outdated data first.
        """

        # -- phase 1: find wallets with no profitability_metrics doc --
        # the $lookup joins 55k users against 55k metrics docs which is expensive.
        # once all wallets have been scanned, skip this and go straight to phase 2.
        # re-check every 10 cycles (~2 hours) in case new wallets were added
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

            never_scanned = [doc['user'] async for doc in self.db.users.aggregate(pipeline)]

            if never_scanned:
                self._phase1_done = False
                count_pipeline = pipeline[:-1] + [{"$count": "total"}]
                count_result = await self.db.users.aggregate(count_pipeline).to_list(None)
                total_unscanned = count_result[0]['total'] if count_result else len(never_scanned)
                remaining = total_unscanned - len(never_scanned)

                logger.info(f"[PHASE 1] {len(never_scanned)} never-scanned wallets "
                            f"({remaining} more waiting)")
                return never_scanned
            else:
                # all wallets have been scanned at least once
                if not self._phase1_done:
                    logger.info("[PHASE 1] complete — all wallets scanned, switching to phase 2")
                self._phase1_done = True

        # -- phase 2: rescan the stalest wallets --
        # all wallets have been scanned at least once, so grab the ones
        # with the oldest last_updated and refresh them
        stalest = await self.db.profitability_metrics.find(
            {},
            {"wallet_address": 1, "last_updated": 1, "_id": 0}
        ).sort("last_updated", 1).limit(batch_size).to_list(batch_size)

        if not stalest:
            logger.info("no wallets in profitability_metrics at all")
            return []

        oldest_ts = stalest[0].get('last_updated', 'unknown')
        newest_ts = stalest[-1].get('last_updated', 'unknown')
        batch = [doc['wallet_address'] for doc in stalest]

        logger.info(f"[PHASE 2] rescanning {len(batch)} stalest wallets "
                    f"(oldest: {oldest_ts}, newest in batch: {newest_ts})")
        return batch

    async def _api_post(self, payload, retries=5, timeout=10):
        """
        All hyperliquid info endpoints use POST to the same URL.
        Retry with exponential backoff on 429s — if we get rate limited the delay
        ratchets up globally so subsequent calls across ALL wallets slow down,
        not just the one that got hit.
        """
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
                    wait = 5 * (2 ** attempt)
                    logger.warning(
                        f"  [429] rate limited on {payload.get('type')}"
                        f" — backing off {wait}s (attempt {attempt+1}/{retries})"
                    )
                    await asyncio.sleep(wait)

                    # debounce: only ratchet the delay once per 5s window.
                    # without this, 5 concurrent wallets all getting 429'd at the
                    # same instant would each multiply self.delay independently,
                    # compounding it from 0.3 to 5+ in a single burst
                    now = time.monotonic()
                    if now - self._last_ratchet > 5:
                        self.delay = min(self.delay * 1.5, 5.0)
                        self._last_ratchet = now
                        logger.warning(f"  [429] global delay bumped to {self.delay:.2f}s")
                    continue

                # 422 = bad request, usually means the wallet address is malformed
                if resp.status_code == 422:
                    return None


            except (httpx.TimeoutException, asyncio.TimeoutError):
                wait = 2 * (attempt + 1)
                logger.warning(f"  timeout on {payload.get('type')} — retrying in {wait}s")
                await asyncio.sleep(wait)

        logger.error(f"  [FAILED] {payload.get('type')} after {retries} attempts — skipping")
        return None

    async def _fetch_all_fills(self, wallet_address, max_fills=10000):
        """
        The userFills endpoint returns max 2000 fills per call. If we get exactly
        2000 back there are probably more, so we paginate backwards in time using
        endTime. We cap at max_fills to avoid spending forever on whales with
        millions of trades.
        """
        try:
            first_page = await self._api_post(
                {"type": "userFills", "user": wallet_address}, timeout=12
            ) or []

            # quick bot check — if the first page alone shows >100 trades/day
            # over less than a week, this is almost certainly a bot. no point
            # paginating through potentially millions more fills
            is_bot = False
            if len(first_page) >= 2000:
                ts_min = min(int(f['time']) for f in first_page)
                ts_max = max(int(f['time']) for f in first_page)
                days = max((ts_max - ts_min) / 86400000, 1)
                tpd = len(first_page) / days
                is_bot = tpd > 100 and days < 7

            if is_bot:
                print(f"  [BOT-FILLS] {wallet_address} — high freq on first page, skipping rest")
                return first_page, True

            all_fills = list(first_page)
            page = first_page

            while len(page) >= 2000 and len(all_fills) < max_fills:
                await asyncio.sleep(self.delay)
                oldest = min(int(f['time']) for f in page)
                page = await self._api_post({
                    "type": "userFills",
                    "user": wallet_address,
                    "endTime": oldest - 1
                }, timeout=12) or []

                if not page:
                    break
                all_fills.extend(page)
                print(f"{len(all_fills)} fills so far")

            return all_fills, False

        except Exception as e:
            logger.error(f"  fill fetch error for {wallet_address}: {e}")
            return [], False

    def _calculate_drawdown(self, fills):
        """
        Walk through fills chronologically, tracking a running PnL total.
        Max drawdown = biggest percentage drop from any peak to the subsequent trough.
        """
        if not fills:
            return 0.0

        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))
        running = 0
        peak = 0
        worst_dd = 0

        for f in sorted_fills:
            running += float(f.get('closedPnl', 0))
            if running > peak:
                peak = running
            if peak > 0:
                dd = ((peak - running) / peak) * 100
                if dd > worst_dd:
                    worst_dd = dd

        return worst_dd

    def _get_fee_tier(self, fee_schedule, user_cross_rate):
        """figure out which VIP tier the user is on based on their cross rate"""
        try:
            tiers = fee_schedule.get('tiers', {}).get('vip', [])
            base = float(fee_schedule.get('cross', 0.00045))

            if float(user_cross_rate) >= base:
                return 0

            for i, tier in enumerate(tiers):
                if float(user_cross_rate) >= float(tier.get('cross', 0)):
                    return i + 1

            return len(tiers)
        except Exception:
            return 0

    async def calculate_profitability(self, wallet_address):
        """
        Main per-wallet logic. Fetches 6 different endpoints from hyperliquid,
        then computes profitability metrics and returns them as a dict.

        The API calls are still sequential within a single wallet because each
        call needs its own rate-limit delay. The concurrency comes from running
        multiple wallets in parallel via the semaphore in _scan_one().
        """
        try:
            state = await self._api_post({"type": "clearinghouseState", "user": wallet_address})
            await asyncio.sleep(self.delay)

            portfolio = await self._api_post({"type": "portfolio", "user": wallet_address})
            await asyncio.sleep(self.delay)

            fees_data = await self._api_post({"type": "userFees", "user": wallet_address})
            await asyncio.sleep(self.delay)

            role_data = await self._api_post({"type": "userRole", "user": wallet_address})
            await asyncio.sleep(self.delay)

            sub_data = await self._api_post({"type": "subAccounts", "user": wallet_address})
            await asyncio.sleep(self.delay)

            vault_data = await self._api_post({"type": "userVaultEquities", "user": wallet_address})
            await asyncio.sleep(self.delay)

            if not state or not portfolio:
                print(f"  missing state or portfolio for {wallet_address}")
                return None

            # -- account basics --
            margin = state.get('marginSummary', {})
            account_value = float(margin.get('accountValue', 0))
            withdrawable = float(state.get('withdrawable', 0))

            unrealized_pnl = sum(
                float(p.get('position', {}).get('unrealizedPnl', 0))
                for p in state.get('assetPositions', [])
            )

            # portfolio comes back as a list of [period_name, data] pairs
            all_time = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
            pnl_history = all_time.get('pnlHistory', []) if all_time else []
            realized_pnl = float(pnl_history[-1][1]) if pnl_history else 0.0
            total_volume = float(all_time.get('vlm', 0)) if all_time else 0.0

            # -- historical charts data --
            historical_pnl = {"day": [], "week": [], "month": [], "allTime": []}
            historical_balance = {"day": [], "week": [], "month": [], "allTime": []}

            for period_data in portfolio:
                name = period_data[0]
                if name not in historical_pnl or not isinstance(period_data[1], dict):
                    continue

                pnl_hist = period_data[1].get('pnlHistory', [])
                historical_pnl[name] = [
                    {"timestamp": int(pt[0]), "pnl": float(pt[1])}
                    for pt in pnl_hist
                ]
                bal_hist = period_data[1].get('accountValueHistory', [])
                historical_balance[name] = [
                    {"timestamp": int(pt[0]), "balance": float(pt[1])}
                    for pt in bal_hist
                ]

            # -- fee info --
            user_cross_rate = 0.0
            user_add_rate = 0.0
            fee_tier = 0
            staking_discount = 0.0

            if fees_data:
                user_cross_rate = float(fees_data.get('userCrossRate', 0))
                user_add_rate = float(fees_data.get('userAddRate', 0))
                fee_schedule = fees_data.get('feeSchedule', {})
                fee_tier = self._get_fee_tier(fee_schedule, user_cross_rate)
                # staking discount can be a dict or missing entirely
                staking_raw = fees_data.get('activeStakingDiscount')
                if isinstance(staking_raw, dict):
                    staking_discount = float(staking_raw.get('discount', 0))

            # -- role & sub accounts --
            user_role = "unknown"
            master_wallet = None
            if role_data:
                user_role = role_data.get('role', 'unknown')
                rd = role_data.get('data', {}) or {}
                if user_role == 'subAccount':
                    master_wallet = rd.get('master')

            sub_accounts = []
            if sub_data:
                sub_accounts = [
                    s.get('subAccountAddress') for s in sub_data
                    if s.get('subAccountAddress')
                ]

            # -- vault depositor check --
            vault_positions = vault_data if vault_data else []
            is_vault_depositor = len(vault_positions) > 0

            # if they've never traded, return early with a minimal document
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

        except Exception as e:
            logger.error(f"  error on {wallet_address}: {e}", exc_info=True)
            return None

        # -- fills & trade stats --
        # this is outside the try/except above because we still want to save
        # the basic account data even if fill fetching blows up
        fills, is_bot_by_fills = await self._fetch_all_fills(wallet_address)

        closing_fills = [f for f in fills if float(f.get('closedPnl', 0)) != 0]
        total_trades = len(closing_fills)

        if fills:
            first_trade = min(int(f['time']) for f in fills)
            last_trade = max(int(f['time']) for f in fills)
            days_active = max((last_trade - first_trade) / 86400000, 1)
            trades_per_day = total_trades / days_active
        else:
            trades_per_day = 0

        wins = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) > 0)
        losses = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) < 0)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0
        max_drawdown = self._calculate_drawdown(fills)

        # -- bot detection --
        # using a scoring system instead of a single check because no single
        # signal is reliable enough on its own. need at least 2 to flag
        bot_signals = sum([
            is_bot_by_fills,                                  # high fill frequency
            (user_cross_rate == 0.0 and total_volume > 0),    # zero fee = likely market maker
            trades_per_day > 100,                             # absurd trade frequency
            total_trades > 50000,                             # massive trade count
        ])
        is_likely_bot = bot_signals >= 2

        if is_likely_bot:
            # for bots we just save minimal data and move on, no point computing
            # all the detailed metrics for an algo nobody's going to look at
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

        # -- open positions --
        open_positions = []
        for pos in state.get('assetPositions', []):
            pd = pos.get('position', {})
            try:
                size = float(pd.get('szi', 0))
            except (ValueError, TypeError):
                size = 0.0

            if size == 0:
                continue

            open_positions.append({
                "asset": pd.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pd.get('entryPx', 0)),
                "unrealized_pnl": round(float(pd.get('unrealizedPnl', 0)), 2)
            })

        total_pnl = realized_pnl + unrealized_pnl
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
            "avg_trade_size_usdc": round(avg_trade_size, 2),
            "win_rate_percentage": round(win_rate, 1),
            "max_drawdown_percentage": round(max_drawdown, 2),
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

    async def _scan_one(self, wallet, index=0):
        """
        Wraps calculate_profitability with the semaphore so we never exceed
        the concurrency limit. The index stagger spreads the initial burst —
        wallet 0 starts immediately, wallet 1 waits 0.5s, wallet 2 waits 1s etc.
        Without this all 6 slots fire clearinghouseState at the exact
        same millisecond and they all get 429'd.

        Each wallet gets assigned a slot number (1-6) so you can see in the
        terminal which slot is doing what at any given time.
        """
        async with self._sem:
            # lazy init the lock inside the event loop
            if self._slot_lock is None:
                self._slot_lock = asyncio.Lock()

            # grab the lowest available slot number
            async with self._slot_lock:
                used = set(self._active_slots.keys())
                slot = next(s for s in range(1, 7) if s not in used)
                self._active_slots[slot] = wallet

            print(f"[SLOT {slot}] → {wallet}")

            try:
                # stagger the start so requests don't all land at once
                await asyncio.sleep(index * 0.5)
                result = await self.calculate_profitability(wallet)
                return result
            finally:
                # free the slot so the next wallet can claim it
                async with self._slot_lock:
                    self._active_slots.pop(slot, None)

    async def scan_batch(self, batch_size=100):
        wallets = await self.get_wallets_to_scan(batch_size)
        if not wallets:
            logger.info("no wallets to scan")
            return 0

        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"[{ts}] scanning {len(wallets)} wallets")

        processed = 0
        profitable = 0
        no_activity = 0
        errors = 0
        bots = 0


        # asyncio.gather runs all wallet scans concurrently (up to the semaphore limit).
        # return_exceptions=True means a single wallet crashing won't kill the whole batch —
        # we just get the exception object back in the results list and handle it below.
        # previously this was a sequential for loop which was painfully slow
        results = await asyncio.gather(
            *(self._scan_one(w, i) for i, w in enumerate(wallets)),
            return_exceptions=True
        )

        # collect all the mongo writes and flush them at the end instead of
        # doing one update_one per wallet. bulk_write with ordered=False lets
        # mongo parallelise the writes internally and saves a ton of round trips
        ops = []

        for wallet, metrics in zip(wallets, results):
            # if _scan_one raised an exception, metrics will be the exception object
            if isinstance(metrics, Exception):
                err_msg = str(metrics).lower()
                if "429" in err_msg or "rate" in err_msg:
                    logger.error(f"  failed on {wallet}: {metrics}")
                    errors += 1
                continue

            if metrics == "bot":
                bots += 1
                processed += 1
            elif metrics:
                ops.append(UpdateOne(
                    {"wallet_address": wallet},
                    {"$set": metrics},
                    upsert=True
                ))
                if not metrics.get('has_trading_activity', False):
                    no_activity += 1
                elif metrics.get('total_pnl_usdc', 0) > 0:
                    profitable += 1
                processed += 1
            else:
                errors += 1

        if ops:
            await self.db.profitability_metrics.bulk_write(ops, ordered=False)

        print(f"\nbatch done:")
        print(f"  processed:    {processed}")
        print(f"  profitable:   {profitable}")
        print(f"  bots:         {bots}")
        print(f"  no activity:  {no_activity}")
        print(f"  errors:       {errors}\n")

        with open(LOG_PATH, "a") as logfile:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logfile.write(
                f"[{now}] processed: {processed} | bots: {bots}"
                f" | errors: {errors}\n"
            )
        return processed

    async def run_continuous(self):
        print("profitability scanner starting up")
        print(f"rate: {60.0 / self.delay:.0f} requests per minute\n")

        await self.setup_indexes()

        cycle = 0
        try:
            while True:
                try:
                    cycle += 1
                    print(f"\n--- cycle {cycle} ---")
                    processed = await self.scan_batch(batch_size=100)

                    if processed == 0:
                        # only happens if the users collection is completely empty.
                        # wait a bit and check again in case wallets get added
                        print("no wallets found at all, sleeping 10 mins")
                        await asyncio.sleep(600)
                    else:
                        # short breather between batches. the per-call delay
                        # handles rate limiting, this is just so we don't
                        # slam mongo with batch after batch nonstop
                        await asyncio.sleep(10)

                except KeyboardInterrupt:
                    print("\nstopped")
                    break
                except Exception as e:
                    print(f"something broke in cycle {cycle}: {e}")
                    print("waiting 5 mins before retrying")
                    await asyncio.sleep(300)
        finally:
            await self.close()


async def main():
    mongo_uri = os.getenv('MONGO_URI')
    scanner = ProfitabilityScanner(mongo_uri, rpm=200)
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
