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


class ProfitabilityScanner:

    def __init__(self, mongo_uri, rpm=50):
        self.client = MongoClient(mongo_uri)
        self.db = self.client['hyperliquid']

        self.delay = 60.0 / rpm  # 1.2 seconds between requests
        self.skip = 0

        self.setup_indexes()

    def setup_indexes(self):
        print("setting up indexes")

        self.db.profitability_metrics.create_index("wallet_address", unique=True)
        self.db.profitability_metrics.create_index([("total_pnl_usdc", -1)])
        self.db.profitability_metrics.create_index("has_trading_activity")
        self.db.profitability_metrics.create_index("account_value")
        self.db.profitability_metrics.create_index("win_rate_percentage")
        self.db.profitability_metrics.create_index("trade_count")
        self.db.profitability_metrics.create_index("is_likely_bot")     # new
        self.db.profitability_metrics.create_index("user_role")         # new
        self.db.profitability_metrics.create_index("fee_tier")          # new

        self.db.users.create_index("user", unique=True)

        print("indexes done\n")


    def get_wallets_to_scan(self, batch_size=100):
        total_users = self.db.users.count_documents({"user": {"$exists": True}})

        if self.skip >= total_users:
            self.skip = 0
            print(f"\n{'='*60}")
            print(f"finished full cycle - went through all {total_users} users")
            print(f"starting again from the top")
            print(f"{'='*60}\n")

        wallets = list(self.db.users.find(
            {"user": {"$exists": True}},
            {"user": 1, "_id": 0}
        ).sort("_id", 1).skip(self.skip).limit(batch_size))

        self.skip += len(wallets)

        start = self.skip - len(wallets) + 1
        end   = self.skip
        print(f"scanning users {start} to {end} of {total_users}")

        return [w['user'] for w in wallets if 'user' in w]


    def _api_post(self, payload, retries=3):
        # centralised post with retry on 429
        for attempt in range(retries):
            try:
                resp = requests.post(
                    "https://api.hyperliquid.xyz/info",
                    json=payload,
                    timeout=10
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429:
                    wait = (attempt + 1) * 3
                    print(f"  429 on {payload.get('type')} - sleeping {wait}s")
                    time.sleep(wait)
                    continue

                if resp.status_code == 422:
                    return None  # wallet has no data for this endpoint, not an error

                print(f"  HTTP {resp.status_code} on {payload.get('type')}")
                return None

            except requests.exceptions.Timeout:
                print(f"  timeout on {payload.get('type')}")
                return None
            except Exception as e:
                print(f"  request error on {payload.get('type')}: {e}")
                return None

        return None


    def _fetch_all_fills_from_api(self, wallet_address):
        all_fills = []

        try:
            fills = self._api_post({"type": "userFills", "user": wallet_address}) or []
            all_fills.extend(fills)

            while len(fills) >= 2000:
                time.sleep(self.delay)

                oldest_time = min(int(f['time']) for f in fills)

                fills = self._api_post({
                    "type":    "userFills",
                    "user":    wallet_address,
                    "endTime": oldest_time - 1
                }) or []

                if not fills:
                    break

                all_fills.extend(fills)
                print(f"    paginating fills... {len(all_fills)} total so far")

        except Exception as e:
            print(f"  fill fetch error for {wallet_address}: {e}")

        return all_fills


    def _calculate_drawdown(self, fills):
        if not fills:
            return 0.0

        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        running_total = 0
        peak          = 0
        max_dd        = 0

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
        # works out which VIP tier the wallet is on based on their actual cross rate
        # tiers go from 0.00045 (base) down as volume increases
        try:
            tiers = fee_schedule.get('tiers', {}).get('vip', [])
            base  = float(fee_schedule.get('cross', 0.00045))

            if float(user_cross_rate) >= base:
                return 0  # base tier

            for i, tier in enumerate(tiers):
                if float(user_cross_rate) >= float(tier.get('cross', 0)):
                    return i + 1

            return len(tiers)  # highest tier
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

            # subAccounts can 429 more easily - extra sleep before it
            time.sleep(2)
            sub_data  = self._api_post({"type": "subAccounts", "user": wallet_address})
            time.sleep(self.delay)

            vault_data = self._api_post({"type": "userVaultEquities", "user": wallet_address})
            time.sleep(self.delay)

            if not state or not portfolio:
                print(f"  missing state or portfolio for {wallet_address}")
                return None
            # debug
            print({wallet_address})
            # print(f"  portfolio response: {str(portfolio_resp.json())[:300]}")  # checking what the response was
            # print(f"  state type: {type(state)}")
            # print(f"  portfolio : {str(portfolio)[:200]}")

            margin         = state.get('marginSummary', {})
            account_value  = float(margin.get('accountValue', 0))
            withdrawable   = float(state.get('withdrawable', 0))


            unrealized_pnl = sum(
                float(pos.get('position', {}).get('unrealizedPnl', 0))
                for pos in state.get('assetPositions', [])
            )

            all_time     = next((p[1] for p in portfolio if p[0] == 'allTime'), None)
            pnl_history  = all_time.get('pnlHistory', []) if all_time else []
            realized_pnl = float(pnl_history[-1][1]) if pnl_history else 0.0
            total_volume = float(all_time.get('vlm', 0)) if all_time else 0.0

            # --- Extract PnL Histories for charts ---
            historical_pnl = {
                "day": [],
                "week": [],
                "month": [],
                "allTime": []
            }

            for period_data in portfolio:
                period_name = period_data[0]
                # we only want these 4 specific periods (ignoring perpDay, perpWeek etc)
                if period_name in historical_pnl and isinstance(period_data[1], dict):
                    hist = period_data[1].get('pnlHistory', [])
                    # format as simple dicts to make frontend charting easier
                    historical_pnl[period_name] = [
                        {"timestamp": int(point[0]), "pnl": float(point[1])}
                        for point in hist
                    ]


            # --- userFees: bot detection + fee tier ---
            user_cross_rate     = 0.0
            user_add_rate       = 0.0
            fee_tier            = 0
            staking_discount    = 0.0
            is_likely_bot       = False

            if fees_data:
                user_cross_rate  = float(fees_data.get('userCrossRate', 0))
                user_add_rate    = float(fees_data.get('userAddRate', 0))
                fee_schedule     = fees_data.get('feeSchedule', {})
                fee_tier         = self._get_fee_tier(fee_schedule, user_cross_rate)
                staking_discount = float(
                    fees_data.get('activeStakingDiscount', {}).get('discount', 0)
                    if isinstance(fees_data.get('activeStakingDiscount'), dict)
                    else 0
                )

                # maker-only (never crosses spread) or earns rebates = likely a bot
                is_likely_bot = (user_cross_rate == 0.0 or user_add_rate < 0)

            # --- userRole: master / subAccount / vaultLeader ---
            user_role     = "unknown"
            master_wallet = None

            if role_data:
                user_role = role_data.get('role', 'unknown')
                rd        = role_data.get('data', {}) or {}

                if user_role == 'subAccount':
                    master_wallet = rd.get('master')

            # --- subAccounts: how many sub-wallets does this master have ---
            sub_account_addresses = []

            if sub_data:
                sub_account_addresses = [
                    s.get('subAccountAddress') for s in sub_data
                    if s.get('subAccountAddress')
                ]

            # --- userVaultEquities: passive vault depositor flag ---
            vault_positions     = vault_data if vault_data else []
            is_vault_depositor  = len(vault_positions) > 0

            if total_volume == 0 and realized_pnl == 0:
                return {
                    "wallet_address":      wallet_address,
                    "has_trading_activity": False,
                    "account_value":       round(account_value, 2),
                    "withdrawable_balance": round(withdrawable, 2),
                    "user_role":           user_role,
                    "master_wallet":       master_wallet,
                    "sub_account_count":   len(sub_account_addresses),
                    "sub_accounts":        sub_account_addresses,
                    "is_likely_bot":       is_likely_bot,
                    "is_vault_depositor":  is_vault_depositor,
                    "last_updated":        datetime.now()
                }

        except Exception as e:
            print(f"  error on {wallet_address}: {e}")
            traceback.print_exc()
            return None

        fills = self._fetch_all_fills_from_api(wallet_address)
        closing_fills = [f for f in fills if float(f.get('closedPnl', 0)) != 0]
        total_trades = len(closing_fills)
        winning_trades = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) > 0)
        losing_trades = sum(1 for f in closing_fills if float(f.get('closedPnl', 0)) < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0
        max_drawdown   = self._calculate_drawdown(fills)

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
                "asset":          pos_data.get('coin', 'UNKNOWN'),
                "direction":      "LONG" if size > 0 else "SHORT",
                "size":           abs(size),
                "entry_price":    float(pos_data.get('entryPx', 0)),
                "unrealized_pnl": round(float(pos_data.get('unrealizedPnl', 0)), 2)
            })

        total_pnl  = realized_pnl + unrealized_pnl
        profit_pct = round((total_pnl / total_volume * 100), 2) if total_volume > 0 else 0

        return {
            "wallet_address":        wallet_address,
            "has_trading_activity":  True,
            "account_value":         round(account_value, 2),
            "withdrawable_balance":  round(withdrawable, 2),
            "total_pnl_usdc":        round(total_pnl, 2),
            "realized_pnl_usdc":     round(realized_pnl, 2),
            "unrealized_pnl_usdc":   round(unrealized_pnl, 2),
            "profit_percentage":     profit_pct,
            "trade_count":           total_trades,
            "historical_pnl":        historical_pnl,
            "winning_trades":        winning_trades,
            "losing_trades":         losing_trades,
            "total_volume_usdc":     round(total_volume, 2),
            "avg_trade_size_usdc":   round(avg_trade_size, 2),
            "win_rate_percentage":   round(win_rate, 1),
            "max_drawdown_percentage": round(max_drawdown, 2),
            "open_positions_count":  len(open_positions),
            "open_positions":        open_positions,
            # new fields
            "user_role":             user_role,
            "master_wallet":         master_wallet,
            "sub_account_count":     len(sub_account_addresses),
            "sub_accounts":          sub_account_addresses,
            "is_likely_bot":         is_likely_bot,
            "user_cross_rate":       user_cross_rate,
            "user_add_rate":         user_add_rate,
            "fee_tier":              fee_tier,
            "staking_discount":      staking_discount,
            "is_vault_depositor":    is_vault_depositor,
            "last_updated":          datetime.now()
        }


    async def scan_batch(self, batch_size=100):
        wallets = self.get_wallets_to_scan(batch_size)

        if not wallets:
            print("no wallets to scan")
            return 0

        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{ts}] scanning {len(wallets)} wallets")

        processed   = 0
        profitable  = 0
        no_activity = 0
        errors      = 0
        bots        = 0

        for wallet in wallets:
            try:
                await asyncio.sleep(self.delay)

                metrics = self.calculate_profitability(wallet)

                if metrics:
                    self.db.profitability_metrics.update_one(
                        {"wallet_address": wallet},
                        {"$set": metrics},
                        upsert=True
                    )

                    if not metrics.get('has_trading_activity', False):
                        no_activity += 1
                    else:
                        if metrics['total_pnl_usdc'] > 0:
                            profitable += 1
                        if metrics.get('is_likely_bot'):
                            bots += 1

                    processed += 1

                    if processed % 10 == 0:
                        print(f"  {processed}/{len(wallets)} done | profitable: {profitable} | bots: {bots} | no activity: {no_activity}")

                else:
                    errors += 1

            except Exception as e:
                print(f"  failed on {wallet}: {e}")
                errors += 1
                continue

        print(f"batch done:")
        print(f"  processed:   {processed}")
        print(f"  profitable:  {profitable}")
        print(f"  bots:        {bots}")
        print(f"  no activity: {no_activity}")
        print(f"  errors:      {errors}\n")

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

                if processed == 0:
                    print("all wallets scanned, sleeping for an hour\n")
                    await asyncio.sleep(3600)
                else:
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
    scanner   = ProfitabilityScanner(mongo_uri, rpm=50)
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
