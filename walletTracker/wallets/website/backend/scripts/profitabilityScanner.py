"""
Continuous profitability scanner for all users in MongoDB
"""

import asyncio
import sys
import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()


class ProfitabilityScanner:
    def __init__(self, mongo_uri, requests_per_minute=50):
        self.client = MongoClient(mongo_uri)
        self.db = self.client['hyperliquid']
        self.delay = 60.0 / requests_per_minute
        self.current_offset = 0

        # Create indexes on startup
        self.setup_indexes()

    def setup_indexes(self):
        """Create indexes for optimal query performance - runs once at startup"""
        print("Setting up database indexes...")

        # Profitability metrics indexes
        self.db.profitability_metrics.create_index("wallet_address", unique=True)
        self.db.profitability_metrics.create_index([("total_pnl_usdc", -1)])  # For leaderboard
        self.db.profitability_metrics.create_index("has_trading_activity")
        self.db.profitability_metrics.create_index("account_value")
        self.db.profitability_metrics.create_index("win_rate_percentage")
        self.db.profitability_metrics.create_index("trade_count")

        # Users collection indexes
        self.db.users.create_index("user", unique=True)

        print("Indexes created/verified successfully\n")

    def get_wallets_to_scan(self, batch_size=100):
        """Get batch of wallets from users collection with offset"""
        total_users = self.db.users.count_documents({"user": {"$exists": True}})

        if self.current_offset >= total_users:
            self.current_offset = 0
            print(f"\n{'='*60}")
            print(f"Completed full cycle through all {total_users} users")
            print(f"Restarting from beginning")
            print(f"{'='*60}\n")

        wallets = list(self.db.users.find(
            {"user": {"$exists": True}},
            {"user": 1, "_id": 0}
        ).skip(self.current_offset).limit(batch_size))

        self.current_offset += len(wallets)

        print(f"Progress: Scanning users {self.current_offset - len(wallets) + 1} to {self.current_offset} of {total_users}")

        return [w['user'] for w in wallets if 'user' in w]

    def calculate_profitability(self, wallet_address):
        """Calculate profitability metrics including balance"""
        import requests

        try:
            response = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "userFills", "user": wallet_address},
                timeout=10
            )

            if response.status_code != 200:
                print(f"  API error for {wallet_address}: HTTP {response.status_code}")
                return None

            fills = response.json()

            state_response = requests.post(
                "https://api.hyperliquid.xyz/info",
                json={"type": "clearinghouseState", "user": wallet_address},
                timeout=10
            )
            state = state_response.json()

            margin_summary = state.get('marginSummary', {})
            account_value = float(margin_summary.get('accountValue', 0))
            withdrawable = float(state.get('withdrawable', 0))

            if not fills or len(fills) == 0:
                return {
                    "wallet_address": wallet_address,
                    "has_trading_activity": False,
                    "account_value": round(account_value, 2),
                    "withdrawable_balance": round(withdrawable, 2),
                    "last_updated": datetime.now()
                }

        except requests.exceptions.Timeout:
            print(f"  Timeout for {wallet_address}")
            return None
        except Exception as e:
            print(f"  API error for {wallet_address}: {e}")
            return None

        realized_pnl = sum(float(fill.get('closedPnl', 0)) for fill in fills)

        unrealized_pnl = 0
        positions = []

        asset_positions = state.get('assetPositions', [])

        for pos in asset_positions:
            position_data = pos.get('position', {})
            size = float(position_data.get('szi', 0))

            if size == 0:
                continue

            entry_price = float(position_data.get('entryPx', 0))
            position_unrealized_pnl = float(position_data.get('unrealizedPnl', 0))
            unrealized_pnl += position_unrealized_pnl

            positions.append({
                "asset": position_data.get('coin', 'UNKNOWN'),
                "direction": "LONG" if size > 0 else "SHORT",
                "size": abs(size),
                "entry_price": entry_price,
                "unrealized_pnl": position_unrealized_pnl
            })

        total_trades = len(fills)
        winning_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) > 0)
        losing_trades = sum(1 for f in fills if float(f.get('closedPnl', 0)) < 0)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

        total_volume = sum(
            float(f.get('px', 0)) * abs(float(f.get('sz', 0)))
            for f in fills
        )

        avg_trade_size = total_volume / total_trades if total_trades > 0 else 0
        max_drawdown = self._calculate_drawdown(fills)
        total_pnl = realized_pnl + unrealized_pnl

        return {
            "wallet_address": wallet_address,
            "has_trading_activity": True,
            "account_value": round(account_value, 2),
            "withdrawable_balance": round(withdrawable, 2),
            "total_pnl_usdc": round(total_pnl, 2),
            "realized_pnl_usdc": round(realized_pnl, 2),
            "unrealized_pnl_usdc": round(unrealized_pnl, 2),
            "profit_percentage": round((total_pnl / total_volume * 100), 2) if total_volume > 0 else 0,
            "trade_count": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "total_volume_usdc": round(total_volume, 2),
            "avg_trade_size_usdc": round(avg_trade_size, 2),
            "win_rate_percentage": round(win_rate, 1),
            "max_drawdown_percentage": round(max_drawdown, 2),
            "open_positions_count": len(positions),
            "open_positions": positions,
            "last_updated": datetime.now()
        }

    def _calculate_drawdown(self, fills):
        """Calculate maximum drawdown percentage"""
        if not fills or len(fills) == 0:
            return 0.0

        sorted_fills = sorted(fills, key=lambda x: x.get('time', 0))

        cumulative_pnl = []
        running_total = 0

        for fill in sorted_fills:
            running_total += float(fill.get('closedPnl', 0))
            cumulative_pnl.append(running_total)

        if not cumulative_pnl:
            return 0.0

        peak = cumulative_pnl[0]
        max_drawdown = 0

        for pnl in cumulative_pnl:
            if pnl > peak:
                peak = pnl

            if peak > 0:
                drawdown = ((peak - pnl) / peak * 100)
                max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

    async def scan_batch(self, batch_size=100):
        """Scan one batch of wallets"""
        wallets = self.get_wallets_to_scan(batch_size)

        if not wallets:
            print("No wallets found.")
            return 0

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Scanning {len(wallets)} wallets...")

        processed = 0
        profitable = 0
        no_activity = 0
        errors = 0

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

                    processed += 1

                    if processed % 10 == 0:
                        print(f"  Progress: {processed}/{len(wallets)} | Profitable: {profitable} | No activity: {no_activity}")
                else:
                    errors += 1

            except Exception as e:
                print(f"  Error processing {wallet}: {e}")
                errors += 1
                continue

        print(f"Batch complete:")
        print(f"  Processed: {processed}")
        print(f"  Profitable: {profitable}")
        print(f"  No activity: {no_activity}")
        print(f"  Errors: {errors}\n")

        return processed

    async def run_continuous(self):
        """Main loop - runs forever"""
        print("=" * 60)
        print("Starting Continuous Profitability Scanner")
        print("=" * 60)
        print(f"Rate limit: {60.0 / self.delay:.0f} requests/minute\n")

        cycle = 0

        while True:
            try:
                cycle += 1
                print(f"\n--- Cycle {cycle} ---")

                processed = await self.scan_batch(batch_size=100)

                if processed == 0:
                    print("No more wallets. Sleeping 1 hour...\n")
                    await asyncio.sleep(3600)
                else:
                    print("Brief pause before next batch...")
                    await asyncio.sleep(30)

            except KeyboardInterrupt:
                print("\n\nScanner stopped by user.")
                break
            except Exception as e:
                print(f"Error in scan cycle: {e}")
                await asyncio.sleep(300)


async def main():
    mongo_uri = os.getenv('MONGO_URI')

    if not mongo_uri:
        print("Error: MONGO_URI not found in .env file")
        return

    scanner = ProfitabilityScanner(mongo_uri, requests_per_minute=50)
    await scanner.run_continuous()


if __name__ == "__main__":
    asyncio.run(main())
