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

    def __init__(self, mongoUri, rpm=200):
        self.client = AsyncIOMotorClient(mongoUri)
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
        self._activeSlots = {}
        self._slotLock = None  # lazy init, asyncio.Lock needs an event loop

        # tracks when we last bumped the delay. when 5 wallets all get 429'd in
        # the same second, we only want to ratchet self.delay ONCE, not 5 times.
        # without this it went 0.3 → 0.45 → 0.67 → 1.01 → 1.52 in one burst
        self._lastRatchet = 0

        # once phase 1 finishes (all wallets scanned at least once), don't
        # need to run the expensive $lookup every single cycle. this counter
        # tracks how many cycles since we last checked for new unscanned wallets.
        # re-checks every 10 cycles (~2 hours) in case new wallets were added
        self._phase1Done = False
        self._cyclesSincePhase1Check = 0

        # indexes get set up in runContinuous() since motor needs an event loop
        self._indexesCreated = False

    async def _getHttp(self):
        """lazy init so we don't create the client until we're inside an event loop"""
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=10)
        return self._http

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def setupIndexes(self):
        if self._indexesCreated:
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

        self._indexesCreated = True
        logger.info("indexes done\n")

    async def getWalletsToScan(self, batchSize=100):
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
        self._cyclesSincePhase1Check += 1
        skipPhase1 = self._phase1Done and self._cyclesSincePhase1Check < 10

        if not skipPhase1:
            self._cyclesSincePhase1Check = 0

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
                {"$limit": batchSize}
            ]

            neverScanned = [doc['user'] async for doc in self.db.users.aggregate(pipeline)]

            if neverScanned:
                self._phase1Done = False
                countPipeline = pipeline[:-1] + [{"$count": "total"}]
                countResult = await self.db.users.aggregate(countPipeline).to_list(None)
                totalUnscanned = countResult[0]['total'] if countResult else len(neverScanned)
                remaining = totalUnscanned - len(neverScanned)

                logger.info(f"[PHASE 1] {len(neverScanned)} never-scanned wallets "
                            f"({remaining} more waiting)")
                return neverScanned
            else:
                # all wallets have been scanned at least once
                if not self._phase1Done:
                    logger.info("[PHASE 1] complete — all wallets scanned, switching to phase 2")
                self._phase1Done = True

        # -- phase 2: rescan the stalest wallets --
        # all wallets have been scanned at least once, so grab the ones
        # with the oldest last_updated and refresh them
        stalest = await self.db.profitability_metrics.find(
            {},
            {"wallet_address": 1, "last_updated": 1, "_id": 0}
        ).sort("last_updated", 1).limit(batchSize).to_list(batchSize)

        if not stalest:
            logger.info("no wallets in profitability_metrics at all")
            return []

        oldestTs = stalest[0].get('last_updated', 'unknown')
        newestTs = stalest[-1].get('last_updated', 'unknown')
        batch = [doc['wallet_address'] for doc in stalest]

        logger.info(f"[PHASE 2] rescanning {len(batch)} stalest wallets "
                    f"(oldest: {oldestTs}, newest in batch: {newestTs})")
        return batch

    async def _apiPost(self, payload, retries=5, timeout=10):
        """
        All hyperliquid info endpoints use POST to the same URL.
        Retry with exponential backoff on 429s — if we get rate limited the delay
        ratchets up globally so subsequent calls across ALL wallets slow down,
        not just the one that got hit.
        """
        http = await self._getHttp()

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
                    if now - self._lastRatchet > 5:
                        self.delay = min(self.delay * 1.5, 5.0)
                        self._lastRatchet = now
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

    async def _fetchAllFills(self, walletAddress, maxFills=10000):
        """
        The userFills endpoint returns max 2000 fills per call. If we get exactly
        2000 back there are probably more, so we paginate backwards in time using
        endTime. We cap at max_fills to avoid spending forever on whales with
        millions of trades.
        """
        try:
            firstPage = await self._apiPost(
                {"type": "userFills", "user": walletAddress}, timeout=12
            ) or []

            # quick bot check — if the first page alone shows >100 trades/day
            # over less than a week, this is almost certainly a bot. no point
            # paginating through potentially millions more fills
            isBot = False
            if len(firstPage) >= 2000:
                ts_min = min(int(f['time']) for f in firstPage)
                ts_max = max(int(f['time']) for f in firstPage)
                days = max((ts_max - ts_min) / 86400000, 1)
                tpd = len(firstPage) / days
                isBot = tpd > 100 and days < 7

            if isBot:
                print(f"  [BOT-FILLS] {walletAddress} — high freq on first page, skipping rest")
                return firstPage, True

            allFills = list(firstPage)
            page = firstPage

            while len(page) >= 2000 and len(allFills) < maxFills:
                await asyncio.sleep(self.delay)
                oldest = min(int(f['time']) for f in page)
                page = await self._apiPost({
                    "type": "userFills",
                    "user": walletAddress,
                    "endTime": oldest - 1
                }, timeout=12) or []

                if not page:
                    break
                allFills.extend(page)
                print(f"{len(allFills)} fills so far")

            return allFills, False

        except Exception as e:
            logger.error(f"  fill fetch error for {walletAddress}: {e}")
            return [], False

    def _calculateDrawdown(self, fills):
        """
        Walk through fills chronologically, tracking a running PnL total.
        Max drawdown = biggest percentage drop from any peak to the subsequent trough.
        """
        if not fills:
            return 0.0

        sortedFills = sorted(fills, key=lambda x: x.get('time', 0))
        running = 0
        peak = 0
        worstDd = 0

        for f in sortedFills:
            running += float(f.get('closedPnl', 0))
            if running > peak:
                peak = running
            if peak > 0:
                dd = ((peak - running) / peak) * 100
                if dd > worstDd:
                    worstDd = dd

        return worstDd

    def _getFeeTier(self, feeSchedule, userCrossRate):
        """figure out which VIP tier the user is on based on their cross rate"""
        try:
            tiers = feeSchedule.get('tiers', {}).get('vip', [])
            base = float(feeSchedule.get('cross', 0.00045))

            if float(userCrossRate) >= base:
                return 0

            for i, tier in enumerate(tiers):
                if float(userCrossRate) >= float(tier.get('cross', 0)):
                    return i + 1

            return len(tiers)
        except Exception:
            return 0

    async def calculateProfitability(self, walletAddress):
        """
        Main per-wallet logic. Fetches 6 different endpoints from hyperliquid,
        then computes profitability metrics and returns them as a dict.

        The API calls are still sequential within a single wallet because each
        call needs its own rate-limit delay. The concurrency comes from running
        multiple wallets in parallel via the semaphore in _scan_one().
        """
        try:
            state = await self._apiPost({"type": "clearinghouseState", "user": walletAddress})
            await asyncio.sleep(self.delay)

            portfolio = await self._apiPost({"type": "portfolio", "user": walletAddress})
            await asyncio.sleep(self.delay)

            fees_data = await self._apiPost({"type": "userFees", "user": walletAddress})
            await asyncio.sleep(self.delay)

            role_data = await self._apiPost({"type": "userRole", "user": walletAddress})
            await asyncio.sleep(self.delay)

            subData = await self._apiPost({"type": "subAccounts", "user": walletAddress})
            await asyncio.sleep(self.delay)

            vaultData = await self._apiPost({"type": "userVaultEquities", "user": walletAddress})
            await asyncio.sleep(self.delay)

            if not state or not portfolio:
                print(f"  missing state or portfolio for {walletAddress}")
                return None

            # -- account basics --
            margin = state.get('marginSummary', {})
            accountValue = float(margin.get('accountValue', 0))
            withdrawable = float(state.get('withdrawable', 0))

            unrealizedPnl = sum(
                float(p.get('position', {}).get('unrealizedPnl', 0))
                for p in state.get('assetPositions', [])
            )

            # portfolio comes back as a list of [period_name, data] pairs
            allTime = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
            pnlHistory = allTime.get('pnlHistory', []) if allTime else []
            realizedPnl = float(pnlHistory[-1][1]) if pnlHistory else 0.0
            totalVolume = float(allTime.get('vlm', 0)) if allTime else 0.0

            # -- historical charts data --
            historicalPnl = {"day": [], "week": [], "month": [], "allTime": []}
            historicalBalance = {"day": [], "week": [], "month": [], "allTime": []}

            for period_data in portfolio:
                name = period_data[0]
                if name not in historicalPnl or not isinstance(period_data[1], dict):
                    continue

                pnlHist = period_data[1].get('pnlHistory', [])
                historicalPnl[name] = [
                    {"timestamp": int(pt[0]), "pnl": float(pt[1])}
                    for pt in pnlHist
                ]
                balHist = period_data[1].get('accountValueHistory', [])
                historicalBalance[name] = [
                    {"timestamp": int(pt[0]), "balance": float(pt[1])}
                    for pt in balHist
                ]

            # -- fee info --
            userCrossRate = 0.0
            userAddRate = 0.0
            feeTier = 0
            stakingDiscount = 0.0

            if fees_data:
                userCrossRate = float(fees_data.get('userCrossRate', 0))
                userAddRate = float(fees_data.get('userAddRate', 0))
                feeSchedule = fees_data.get('feeSchedule', {})
                feeTier = self._getFeeTier(feeSchedule, userCrossRate)
                # staking discount can be a dict or missing entirely
                stakingRaw = fees_data.get('activeStakingDiscount')
                if isinstance(stakingRaw, dict):
                    stakingDiscount = float(stakingRaw.get('discount', 0))

            # -- role & sub accounts --
            userRole = "unknown"
            masterWallet = None
            if role_data:
                userRole = role_data.get('role', 'unknown')
                rd = role_data.get('data', {}) or {}
                if userRole == 'subAccount':
                    masterWallet = rd.get('master')

            subAccounts = []
            if subData:
                subAccounts = [
                    s.get('subAccountAddress') for s in subData
                    if s.get('subAccountAddress')
                ]

            # -- vault depositor check --
            vaultPositions = vaultData if vaultData else []
            isVaultDepositor = len(vaultPositions) > 0

            # if they've never traded, return early with a minimal document
            if totalVolume == 0 and realizedPnl == 0:
                return {
                    "wallet_address": walletAddress,
                    "has_trading_activity": False,
                    "account_value": round(accountValue, 2),
                    "withdrawable_balance": round(withdrawable, 2),
                    "user_role": userRole,
                    "master_wallet": masterWallet,
                    "sub_account_count": len(subAccounts),
                    "sub_accounts": subAccounts,
                    "is_likely_bot": False,
                    "is_vault_depositor": isVaultDepositor,
                    "last_updated": datetime.now()
                }

        except Exception as e:
            logger.error(f"  error on {walletAddress}: {e}", exc_info=True)
            return None

        # -- fills & trade stats --
        # this is outside the try/except above because we still want to save
        # the basic account data even if fill fetching blows up
        fills, isBotByFills = await self._fetchAllFills(walletAddress)

        closingFills = [f for f in fills if float(f.get('closedPnl', 0)) != 0]
        totalTrades = len(closingFills)

        if fills:
            firstTrade = min(int(f['time']) for f in fills)
            lastTrade = max(int(f['time']) for f in fills)
            daysActive = max((lastTrade - firstTrade) / 86400000, 1)
            tradesPerDay = totalTrades / daysActive
        else:
            tradesPerDay = 0

        wins = sum(1 for f in closingFills if float(f.get('closedPnl', 0)) > 0)
        losses = sum(1 for f in closingFills if float(f.get('closedPnl', 0)) < 0)
        winRate = (wins / totalTrades * 100) if totalTrades > 0 else 0
        avgTradeSize = totalVolume / totalTrades if totalTrades > 0 else 0
        maxDrawdown = self._calculateDrawdown(fills)

        # -- bot detection --
        # using a scoring system instead of a single check because no single
        # signal is reliable enough on its own. need at least 2 to flag
        botSignals = sum([
            isBotByFills,                                  # high fill frequency
            (userCrossRate == 0.0 and totalVolume > 0),    # zero fee = likely market maker
            tradesPerDay > 100,                             # absurd trade frequency
            totalTrades > 50000,                             # massive trade count
        ])
        isLikelyBot = botSignals >= 2

        if isLikelyBot:
            # for bots we just save minimal data and move on, no point computing
            # all the detailed metrics for an algo nobody's going to look at
            await self.db.profitability_metrics.update_one(
                {"wallet_address": walletAddress},
                {"$set": {
                    "wallet_address": walletAddress,
                    "is_likely_bot": True,
                    "has_trading_activity": True,
                    "account_value": round(accountValue, 2),
                    "total_volume_usdc": round(totalVolume, 2),
                    "user_role": userRole,
                    "last_updated": datetime.now()
                }},
                upsert=True
            )
            return "bot"

        # -- open positions --
        openPositions = []
        for pos in state.get('assetPositions', []):
            pd = pos.get('position', {})
            try:
                size = float(pd.get('szi', 0))
            except (ValueError, TypeError):
                size = 0.0

            if size == 0:
                continue

            openPositions.append({
                "asset": pd.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pd.get('entryPx', 0)),
                "unrealized_pnl": round(float(pd.get('unrealizedPnl', 0)), 2)
            })

        totalPnl = realizedPnl + unrealizedPnl
        profitPct = round((totalPnl / totalVolume * 100), 2) if totalVolume > 0 else 0

        return {
            "wallet_address": walletAddress,
            "has_trading_activity": True,
            "account_value": round(accountValue, 2),
            "withdrawable_balance": round(withdrawable, 2),
            "total_pnl_usdc": round(totalPnl, 2),
            "realized_pnl_usdc": round(realizedPnl, 2),
            "unrealized_pnl_usdc": round(unrealizedPnl, 2),
            "profit_percentage": profitPct,
            "trade_count": totalTrades,
            "historical_pnl": historicalPnl,
            "historical_balance": historicalBalance,
            "winning_trades": wins,
            "losing_trades": losses,
            "total_volume_usdc": round(totalVolume, 2),
            "avg_trade_size_usdc": round(avgTradeSize, 2),
            "win_rate_percentage": round(winRate, 1),
            "max_drawdown_percentage": round(maxDrawdown, 2),
            "open_positions_count": len(openPositions),
            "open_positions": openPositions,
            "user_role": userRole,
            "master_wallet": masterWallet,
            "sub_account_count": len(subAccounts),
            "sub_accounts": subAccounts,
            "is_likely_bot": False,
            "user_cross_rate": userCrossRate,
            "user_add_rate": userAddRate,
            "fee_tier": feeTier,
            "staking_discount": stakingDiscount,
            "is_vault_depositor": isVaultDepositor,
            "last_updated": datetime.now()
        }

    async def _scanOne(self, wallet, index=0):
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
            if self._slotLock is None:
                self._slotLock = asyncio.Lock()

            # grab the lowest available slot number
            async with self._slotLock:
                used = set(self._activeSlots.keys())
                slot = next(s for s in range(1, 7) if s not in used)
                self._activeSlots[slot] = wallet

            print(f"[SLOT {slot}] → {wallet}")

            try:
                # stagger the start so requests don't all land at once
                await asyncio.sleep(index * 0.5)
                result = await self.calculateProfitability(wallet)
                return result
            finally:
                # free the slot so the next wallet can claim it
                async with self._slotLock:
                    self._activeSlots.pop(slot, None)

    async def scanBatch(self, batchSize=100):
        wallets = await self.getWalletsToScan(batchSize)
        if not wallets:
            logger.info("no wallets to scan")
            return 0

        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"[{ts}] scanning {len(wallets)} wallets")

        processed = 0
        profitable = 0
        noActivity = 0
        errors = 0
        bots = 0


        # asyncio.gather runs all wallet scans concurrently (up to the semaphore limit).
        # return_exceptions=True means a single wallet crashing won't kill the whole batch —
        # we just get the exception object back in the results list and handle it below.
        # previously this was a sequential for loop which was painfully slow
        results = await asyncio.gather(
            *(self._scanOne(w, i) for i, w in enumerate(wallets)),
            return_exceptions=True
        )

        # collect all the mongo writes and flush them at the end instead of
        # doing one update_one per wallet. bulk_write with ordered=False lets
        # mongo parallelise the writes internally and saves a ton of round trips
        ops = []

        for wallet, metrics in zip(wallets, results):
            # if _scan_one raised an exception, metrics will be the exception object
            if isinstance(metrics, Exception):
                errMsg = str(metrics).lower()
                if "429" in errMsg or "rate" in errMsg:
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
                    noActivity += 1
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
        print(f"  no activity:  {noActivity}")
        print(f"  errors:       {errors}\n")

        with open(LOG_PATH, "a") as logfile:
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logfile.write(
                f"[{now}] processed: {processed} | bots: {bots}"
                f" | errors: {errors}\n"
            )
        return processed

    async def runContinuous(self):
        print("profitability scanner starting up")
        print(f"rate: {60.0 / self.delay:.0f} requests per minute\n")

        await self.setupIndexes()

        cycle = 0
        try:
            while True:
                try:
                    cycle += 1
                    print(f"\n--- cycle {cycle} ---")
                    processed = await self.scanBatch(batchSize=100)

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
    mongoUri = os.getenv('MONGO_URI')
    scanner = ProfitabilityScanner(mongoUri, rpm=200)
    await scanner.runContinuous()


if __name__ == "__main__":
    asyncio.run(main())
