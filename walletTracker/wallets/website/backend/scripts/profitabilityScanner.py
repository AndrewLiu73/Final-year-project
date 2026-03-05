# profitability scanner - scans wallets and calculates their pnl etc
# runs continuously on the CS server

import asyncio
import sys
import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
import requests
import time
import traceback

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner.log")


class ProfitabilityScanner:

    def __init__(self, mongo_uri, rpm=200):
        self.client = MongoClient(mongo_uri)
        self.db = self.client['hyperliquid']

        self.delay = 60.0 / rpm
        self.last_id = None

        self.setup_indexes()

    def setup_indexes(self):
        print("setting up indexes")

        self.db.profitability_metrics.create_index("wallet_address", unique=True)
        self.db.profitability_metrics.create_index([("total_pnl_usdc", -1)])
        self.db.profitability_metrics.create_index("has_trading_activity")
        self.db.profitability_metrics.create_index("account_value")
        self.db.profitability_metrics.create_index("win_rate_percentage")
        self.db.profitability_metrics.create_index("trade_count")
        self.db.profitability_metrics.create_index("is_likely_bot")
        self.db.profitability_metrics.create_index("user_role")
        self.db.profitability_metrics.create_index("fee_tier")

        self.db.users.create_index("user", unique=True)

        print("indexes done\n")

    def get_wallets_to_scan(self, batch_size=100):
        query = {"user": {"$exists": True}}
        if self.last_id is not None:
            query["_id"] = {"$lt": self.last_id} #O(log n)

        wallets = list(self.db.users.find(
            query,
            {"user": 1, "_id": 1}
        ).sort("_id", -1).limit(batch_size))

        if not wallets:
            self.last_id = None
            print(f"\nwent through all users, starting again\n")
            return []

        self.last_id = wallets[-1]["_id"]
        print(f"scanning {len(wallets)} users | last_id: {self.last_id}")
        return [w['user'] for w in wallets if 'user' in w]

    def _api_post(self, payload, retries=5, timeout=10):
        for attempt in range(retries):
            try:
                resp = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json=payload,
                    timeout=timeout
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429:
                    wait = 5 * (2 ** attempt)
                    print(f"  [429] rate limited on {payload.get('type')} "
                          f"— backing off {wait}s (attempt {attempt + 1}/{retries})")
                    time.sleep(wait)
                    self.delay = min(self.delay * 1.5, 10.0)
                    print(f"  [429] global delay increased to {self.delay:.2f}s")
                    continue

                if resp.status_code == 422:
                    return None

                print(f"  HTTP {resp.status_code} on {payload.get('type')}")
                return None

            except requests.exceptions.Timeout:
                wait = 2 * (attempt + 1)
                print(f"  timeout on {payload.get('type')} — retrying in {wait}s")
                time.sleep(wait)

        print(f"  [FAILED] {payload.get('type')} after {retries} attempts — skipping")
        return None

    def _fetch_all_fills_from_api(self, wallet_address, max_fills=10000):
        try:
            first_page = self._api_post(
                {"type": "userFills", "user": wallet_address}, timeout=12
            ) or []

            is_bot_by_fills = False

            if len(first_page) >= 2000:
                first_ts = min(int(f['time']) for f in first_page)
                last_ts = max(int(f['time']) for f in first_page)
                days = max((last_ts - first_ts) / 86400000, 1)
                tpd = len(first_page) / days

                is_bot_by_fills = tpd > 100 and days < 7 #more than 100 trades per day in less than 7 days

            if is_bot_by_fills:
                print(f"  [BOT-FILLS] {wallet_address} — high frequency on first page, skipping pagination")
                return first_page, True

            all_fills = list(first_page)
            fills = first_page

            while len(fills) >= 2000 and len(all_fills) < max_fills:
                time.sleep(self.delay)
                oldest_time = min(int(f['time']) for f in fills)
                fills = self._api_post({
                    "type": "userFills",
                    "user": wallet_address,
                    "endTime": oldest_time - 1
                }, timeout=12) or []
                if not fills:
                    break
                all_fills.extend(fills)
                print(f"    paginating fills... {len(all_fills)} total so far")

            return all_fills, False

        except Exception as e:
            print(f"  fill fetch error for {wallet_address}: {e}")
            return [], False

    def _calculate_drawdown(self, fills):
        if not fills:
            return 0.0

        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        running_total = 0
        peak = 0
        max_dd = 0

        for fill in sorted_fills:
            running_total += float(fill.get('closedPnl', 0))

            if running_total > peak:
                peak = running_total

            if peak > 0:
                dd = ((peak - running_total) / peak) * 100
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def _get_fee_tier(self, fee_schedule, user_cross_rate):
        try:
            tiers = fee_schedule.get('tiers', {}).get('vip', [])
            base = float(fee_schedule.get('cross', 0.00045))

            if float(user_cross_rate) >= base:
                return 0

            for i, tier in enumerate(tiers):
                if float(user_cross_rate) >= float(tier.get('cross', 0)):
                    return i + 1

            return len(tiers)
        except:
            return 0

    def calculate_profitability(self, wallet_address):
        try:
            state = self._api_post({"type": "clearinghouseState", "user": wallet_address})
            time.sleep(self.delay)

            portfolio = self._api_post({"type": "portfolio", "user": wallet_address})
            time.sleep(self.delay)

            fees_data = self._api_post({"type": "userFees", "user": wallet_address})
            time.sleep(self.delay)

            role_data = self._api_post({"type": "userRole", "user": wallet_address})
            time.sleep(self.delay)

            sub_data = self._api_post({"type": "subAccounts", "user": wallet_address})
            time.sleep(self.delay)

            vault_data = self._api_post({"type": "userVaultEquities", "user": wallet_address})
            time.sleep(self.delay)

            if not state or not portfolio:
                print(f"  missing state or portfolio for {wallet_address}")
                return None
            # debug
            print(wallet_address)
            # print(f"  portfolio response: {str(portfolio_resp.json())[:300]}")  # checking what the response was
            # print(f"  state type: {type(state)}")
            # print(f"  portfolio : {str(portfolio)[:200]}")

            margin = state.get('marginSummary', {})
            account_value = float(margin.get('accountValue', 0))
            withdrawable = float(state.get('withdrawable', 0))

            unrealized_pnl = sum(
                float(pos.get('position', {}).get('unrealizedPnl', 0))
                for pos in state.get('assetPositions', [])
            )

            all_time = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
            pnl_history = all_time.get('pnlHistory', []) if all_time else []
            realized_pnl = float(pnl_history[-1][1]) if pnl_history else 0.0
            total_volume = float(all_time.get('vlm', 0)) if all_time else 0.0

            historical_pnl = {
                "day": [],
                "week": [],
                "month": [],
                "allTime": []
            }
            historical_balance = {
                "day": [],
                "week": [],
                "month": [],
                "allTime": []
            }

            for period_data in portfolio:
                period_name = period_data[0]
                if period_name in historical_pnl and isinstance(period_data[1], dict):
                    hist = period_data[1].get('pnlHistory', [])
                    historical_pnl[period_name] = [
                        {"timestamp": int(point[0]), "pnl": float(point[1])}
                        for point in hist
                    ]

                    bal_hist = period_data[1].get('accountValueHistory', [])
                    historical_balance[period_name] = [
                        {"timestamp": int(p[0]), "balance": float(p[1])}
                        for p in bal_hist
                    ]

            user_cross_rate = 0.0
            user_add_rate = 0.0
            fee_tier = 0
            staking_discount = 0.0

            if fees_data:
                user_cross_rate = float(fees_data.get('userCrossRate', 0))
                user_add_rate = float(fees_data.get('userAddRate', 0))
                fee_schedule = fees_data.get('feeSchedule', {})
                fee_tier = self._get_fee_tier(fee_schedule, user_cross_rate)
                staking_discount = float(
                    fees_data.get('activeStakingDiscount', {}).get('discount', 0)
                    if isinstance(fees_data.get('activeStakingDiscount'), dict)
                    else 0
                )



            user_role = "unknown"
            master_wallet = None

            if role_data:
                user_role = role_data.get('role', 'unknown')
                rd = role_data.get('data', {}) or {}

                if user_role == 'subAccount':
                    master_wallet = rd.get('master')

            sub_account_addresses = []

            if sub_data:
                sub_account_addresses = [
                    s.get('subAccountAddress') for s in sub_data
                    if s.get('subAccountAddress')
                ]

            vault_positions = vault_data if vault_data else []
            is_vault_depositor = len(vault_positions) > 0

            if total_volume == 0 and realized_pnl == 0:
                return {
                    "wallet_address": wallet_address,
                    "has_trading_activity": False,
                    "account_value": round(account_value, 2),
                    "withdrawable_balance": round(withdrawable, 2),
                    "user_role": user_role,
                    "master_wallet": master_wallet,
                    "sub_account_count": len(sub_account_addresses),
                    "sub_accounts": sub_account_addresses,
                    "is_likely_bot":False,
                    "is_vault_depositor": is_vault_depositor,
                    "last_updated": datetime.now()
                }

        except Exception as e:
            print(f"  error on {wallet_address}: {e}")
            traceback.print_exc()
            return None

        fills, is_bot_by_fills = self._fetch_all_fills_from_api(wallet_address)

        closing_fills = [f for f in fills if float(f.get('closedPnl', 0)) != 0]
        total_trades = len(closing_fills)

        if fills:
            first_trade_day = min(int(f['time']) for f in fills)
            last_trade_day = max(int(f['time']) for f in fills)
            days_active = max((last_trade_day - first_trade_day) / 86400000, 1)
            trades_per_day = total_trades / days_active
        else:
            trades_per_day = 0

        winning_trades = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) > 0)
        losing_trades = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0
        max_drawdown = self._calculate_drawdown(fills)

        bot_signals = 0
        bot_signals += 1 if is_bot_by_fills else 0
        bot_signals += 1 if (user_cross_rate == 0.0 and total_volume > 0) else 0
        bot_signals += 1 if trades_per_day > 100 else 0
        bot_signals += 1 if total_trades > 50000 else 0

        is_likely_bot = bot_signals >= 2

        if is_likely_bot:
            self.db.profitability_metrics.update_one(
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
        for pos in state.get('assetPositions', []):
            pos_data = pos.get('position', {})

            try:
                size = float(pos_data.get('szi', 0))
            except:
                size = 0.0

            if size == 0:
                continue

            open_positions.append({
                "asset": pos_data.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": float(pos_data.get('entryPx', 0)),
                "unrealized_pnl": round(float(pos_data.get('unrealizedPnl', 0)), 2)
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
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_volume_usdc": round(total_volume, 2),
            "avg_trade_size_usdc": round(avg_trade_size, 2),
            "win_rate_percentage": round(win_rate, 1),
            "max_drawdown_percentage": round(max_drawdown, 2),
            "open_positions_count": len(open_positions),
            "open_positions": open_positions,
            "user_role": user_role,
            "master_wallet": master_wallet,
            "sub_account_count": len(sub_account_addresses),
            "sub_accounts": sub_account_addresses,
            "is_likely_bot": is_likely_bot,
            "user_cross_rate": user_cross_rate,
            "user_add_rate": user_add_rate,
            "fee_tier": fee_tier,
            "staking_discount": staking_discount,
            "is_vault_depositor": is_vault_depositor,
            "last_updated": datetime.now()
        }

    async def scan_batch(self, batch_size=100):
        wallets = self.get_wallets_to_scan(batch_size)

        if not wallets:
            print("no wallets to scan")
            return 0

        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] scanning {len(wallets)} wallets")

        processed = 0
        profitable = 0
        no_activity = 0
        errors = 0
        bots = 0
        rate_limited = 0

        for wallet in wallets:
            try:
                await asyncio.sleep(self.delay)

                metrics = self.calculate_profitability(wallet)

                if metrics == "bot":
                    bots += 1
                    processed += 1

                elif metrics:
                    self.db.profitability_metrics.update_one(
                        {"wallet_address": wallet},
                        {"$set": metrics},
                        upsert=True
                    )
                    if not metrics.get('has_trading_activity', False):
                        no_activity += 1
                    else:
                        if metrics.get('total_pnl_usdc', 0) > 0:
                            profitable += 1
                    processed += 1

                    if processed % 10 == 0:
                        print(
                            f"  {processed}/{len(wallets)} done | profitable: {profitable} | bots: {bots} | no activity: {no_activity}")

                else:
                    errors += 1
            except Exception as e:
                err_msg = str(e).lower()

                if "429" in err_msg or "rate" in err_msg:
                    rate_limited += 1
                    print(f"  [RATE LIMIT] {wallet} — sleeping 30s before continuing")
                    await asyncio.sleep(30)
                else:
                    print(f"  failed on {wallet}: {e}")
                    errors += 1

                continue

        print(f"batch done:")
        print(f"  processed:    {processed}")
        print(f"  profitable:   {profitable}")
        print(f"  bots:         {bots}")
        print(f"  no activity:  {no_activity}")
        print(f"  rate limited: {rate_limited}")
        print(f"  errors:       {errors}\n")

        with open(LOG_PATH, "a") as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{ts}] processed: {processed} | bots: {bots} | rate_limited: {rate_limited} | errors: {errors}\n")
        return processed

    async def run_continuous(self):
        print("profitability scanner starting up")
        print(f"rate: {60.0 / self.delay:.0f} requests per minute\n")

        cycle = 0

        while True:
            try:
                cycle += 1
                print(f"\n--- cycle {cycle} ---")
                processed = await self.scan_batch(batch_size=100)

                await asyncio.sleep(30)

            except KeyboardInterrupt:
                print("\nstopped")
                break
            except Exception as e:
                print(f"something broke in cycle {cycle}: {e}")
                print("waiting 5 mins before retrying")
                await asyncio.sleep(300)


async def main():
    mongo_uri = os.getenv('MONGO_URI')
    scanner = ProfitabilityScanner(mongo_uri, rpm=200)
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
