"""
Find Large Open Trades — runs continuously (every 60s by default).
Queries profitability_metrics for large open positions.
Saves results to the 'open_positions' MongoDB collection (upserts, never duplicates).
"""

import os
import time
import logging
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("large_positions")


class LargeTradesFinder:


    def __init__(self, mongo_uri):
        self.client = MongoClient(mongo_uri)
        self.db = self.client['hyperliquid']
        self.setup_indexes()

    def setup_indexes(self):
        # unique key per position: wallet + asset + direction
        self.db["open_positions"].create_index(
            [("wallet_address", 1), ("asset", 1), ("direction", 1)],
            unique=True
        )
        self.db["open_positions"].create_index([("notional_usd", -1)])
        self.db["open_positions"].create_index([("asset", 1)])
        self.db["open_positions"].create_index([("direction", 1)])
        self.db["open_positions"].create_index([("unrealized_pnl", -1)])

        self.db["asset_concentration"].create_index("asset", unique=True)
        self.db["asset_concentration"].create_index([("total_notional", -1)])
        logger.info("indexes ready")

    def find_large_positions(self, min_notional_usd=10000, min_unrealized_pnl=None, asset=None):
        """
        Find users with large open positions.

        Args:
            min_notional_usd: Minimum position size in USD (entry_price * size)
            min_unrealized_pnl: Minimum unrealized PnL (can be negative to find big losses)
            asset: Filter by specific asset (e.g., "BTC", "ETH")

        Returns:
            List of positions with wallet info
        """
        # Build the aggregation pipeline
        pipeline = [
            # Only look at wallets with open positions
            {"$match": {
                "open_positions_count": {"$gt": 0},
                "is_likely_bot": {"$ne": True}
            }},
            # Unwind the open_positions array so we can filter individual positions
            {"$unwind": "$open_positions"},
            # Calculate notional value for each position
            {"$addFields": {
                "open_positions.notional_usd": {
                    "$multiply": ["$open_positions.size", "$open_positions.entry_price"]
                }
            }}
        ]

        # Build match conditions for the position itself
        position_match = {}

        if min_notional_usd:
            position_match["open_positions.notional_usd"] = {"$gte": min_notional_usd}

        if min_unrealized_pnl is not None:
            position_match["open_positions.unrealized_pnl"] = {"$gte": min_unrealized_pnl}

        if asset:
            position_match["open_positions.asset"] = asset.upper()

        if position_match:
            pipeline.append({"$match": position_match})

        # Sort by notional value descending
        pipeline.append({"$sort": {"open_positions.notional_usd": -1}})

        # Project the fields we want to see
        pipeline.append({
            "$project": {
                "wallet_address": 1,
                "account_value": 1,
                "total_pnl_usdc": 1,
                "unrealized_pnl_usdc": 1,
                "win_rate_percentage": 1,
                "trade_count": 1,
                "last_updated": 1,
                "position": "$open_positions"
            }
        })

        results = list(self.db.profitability_metrics.aggregate(pipeline))
        return results

    def save_positions(self, positions):
        """
        Upsert positions into the open_positions collection.
        Key = wallet_address + asset + direction so each position is one document.
        Positions that no longer qualify get removed.
        """
        now = datetime.now()
        coll = self.db["open_positions"]

        # build bulk upserts
        ops = []
        seen_keys = set()
        for p in positions:
            pos = p['position']
            key = {
                "wallet_address": p['wallet_address'],
                "asset": pos['asset'],
                "direction": pos['direction'],
            }
            seen_keys.add((p['wallet_address'], pos['asset'], pos['direction']))

            ops.append(UpdateOne(
                key,
                {"$set": {
                    **key,
                    "size": pos['size'],
                    "entry_price": pos['entry_price'],
                    "notional_usd": pos['notional_usd'],
                    "unrealized_pnl": pos['unrealized_pnl'],
                    "account_value": p.get('account_value', 0),
                    "total_pnl_usdc": p.get('total_pnl_usdc', 0),
                    "win_rate_percentage": p.get('win_rate_percentage', 0),
                    "trade_count": p.get('trade_count', 0),
                    "last_updated": now,
                }},
                upsert=True
            ))

        if ops:
            result = coll.bulk_write(ops, ordered=False)
            logger.info(f"positions: {result.upserted_count} new, "
                        f"{result.modified_count} updated")

        # remove positions that no longer qualify (closed or below threshold)
        all_docs = coll.find({}, {"wallet_address": 1, "asset": 1, "direction": 1})
        stale_ids = []
        for doc in all_docs:
            k = (doc['wallet_address'], doc['asset'], doc['direction'])
            if k not in seen_keys:
                stale_ids.append(doc['_id'])

        if stale_ids:
            coll.delete_many({"_id": {"$in": stale_ids}})
            logger.info(f"removed {len(stale_ids)} closed/stale positions")

    def save_concentration(self, min_positions=3):
        """
        Compute asset concentration and upsert into asset_concentration collection.
        """
        pipeline = [
            {"$match": {
                "open_positions_count": {"$gt": 0},
                "is_likely_bot": {"$ne": True}
            }},
            {"$unwind": "$open_positions"},
            {"$addFields": {
                "open_positions.notional_usd": {
                    "$multiply": ["$open_positions.size", "$open_positions.entry_price"]
                }
            }},
            {"$group": {
                "_id": "$open_positions.asset",
                "total_positions": {"$sum": 1},
                "total_notional": {"$sum": "$open_positions.notional_usd"},
                "total_unrealized_pnl": {"$sum": "$open_positions.unrealized_pnl"},
                "longs": {
                    "$sum": {"$cond": [{"$eq": ["$open_positions.direction", "LONG"]}, 1, 0]}
                },
                "shorts": {
                    "$sum": {"$cond": [{"$eq": ["$open_positions.direction", "SHORT"]}, 1, 0]}
                }
            }},
            {"$match": {"total_positions": {"$gte": min_positions}}},
            {"$sort": {"total_notional": -1}}
        ]

        results = list(self.db.profitability_metrics.aggregate(pipeline))
        now = datetime.now()
        coll = self.db["asset_concentration"]

        seen_assets = set()
        ops = []
        for r in results:
            asset = r['_id']
            seen_assets.add(asset)
            ops.append(UpdateOne(
                {"asset": asset},
                {"$set": {
                    "asset": asset,
                    "total_positions": r['total_positions'],
                    "total_notional": r['total_notional'],
                    "total_unrealized_pnl": r['total_unrealized_pnl'],
                    "longs": r['longs'],
                    "shorts": r['shorts'],
                    "last_updated": now,
                }},
                upsert=True
            ))

        if ops:
            res = coll.bulk_write(ops, ordered=False)
            logger.info(f"concentration: {res.upserted_count} new, "
                        f"{res.modified_count} updated")

        # remove assets that dropped below threshold
        coll.delete_many({"asset": {"$nin": list(seen_assets)}})

        return results

    def print_results(self, positions):
        """Pretty print the results"""
        if not positions:
            print("\nNo positions found matching the criteria.")
            return

        print(f"\nShowing {len(positions)} positions:\n")

        print("=" * 120)

        for i, p in enumerate(positions, 1):
            pos = p['position']
            notional = pos['notional_usd']

            # Color code based on PnL
            pnl = pos['unrealized_pnl']
            pnl_str = f"${pnl:,.2f}"
            if pnl > 0:
                pnl_indicator = "[+]"
            elif pnl < 0:
                pnl_indicator = "[-]"
            else:
                pnl_indicator = "[=]"

            print(f"#{i:3d} | {pos['asset']:8s} | {pos['direction']:5s} | ${notional:15,.2f}")
            print(f"      Wallet: {p['wallet_address']}")
            print(f"      Position: {pos['size']:,.4f} @ ${pos['entry_price']:,.2f}")
            print(f"      Unrealized PnL: {pnl_indicator} {pnl_str}")
            print(f"      Account Value: ${p.get('account_value', 0):,.2f} | "
                  f"Win Rate: {p.get('win_rate_percentage', 0):.1f}% | "
                  f"Trades: {p.get('trade_count', 0):,}")

            last_updated = p.get('last_updated')
            if last_updated:
                if isinstance(last_updated, str):
                    print(f"      Last Updated: {last_updated}")
                else:
                    print(f"      Last Updated: {last_updated.strftime('%Y-%m-%d %H:%M:%S')}")

            print("-" * 120)

        # Summary stats
        total_notional = sum(p['position']['notional_usd'] for p in positions)
        total_upnl = sum(p['position']['unrealized_pnl'] for p in positions)

        print(f"\nSummary:")
        print(f"  Total Positions Shown: {len(positions)}")
        print(f"  Total Notional: ${total_notional:,.2f}")
        print(f"  Total Unrealized PnL: ${total_upnl:,.2f}")
        print("=" * 120)

    def print_concentration(self, results):
        """
        Print asset concentration from pre-computed results.
        """
        if not results:
            print("\nNo asset concentration data.")
            return

        print(f"\nAsset Concentration ({len(results)} assets):\n")
        print("=" * 100)
        print(f"{'Asset':<10} {'Positions':>10} {'Total Notional':>20} {'Total uPnL':>20} {'L/S Ratio'}")
        print("-" * 100)

        for r in results:
            asset = r['_id']
            positions = r['total_positions']
            notional = r['total_notional']
            upnl = r['total_unrealized_pnl']
            longs = r['longs']
            shorts = r['shorts']
            ls_ratio = f"{longs}/{shorts}"

            print(f"{asset:<10} {positions:>10,} ${notional:>18,.2f} ${upnl:>18,.2f}  {ls_ratio}")

        print("=" * 100)

    def close(self):
        self.client.close()


def main():
    min_notional = 10000
    asset = None
    top = 20
    interval = 60

    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("Error: MONGO_URI not found in environment variables")
        return

    finder = LargeTradesFinder(mongo_uri)

    # track previous cycle to detect changes
    prev_snapshot = set()

    try:
        cycle = 0
        while True:
            cycle += 1

            positions = finder.find_large_positions(
                min_notional_usd=min_notional,
                asset=asset,
            )

            # save ALL qualifying positions to MongoDB (upsert)
            finder.save_positions(positions)
            concentration = finder.save_concentration(min_positions=3)

            # build a snapshot of the current top positions so we can detect changes
            top_positions = positions[:top]
            current_snapshot = set()
            for p in top_positions:
                pos = p['position']
                current_snapshot.add((p['wallet_address'], pos['asset'], pos['direction']))

            # on first run always print, after that only print when something changed
            new_entries = current_snapshot - prev_snapshot
            closed_entries = prev_snapshot - current_snapshot
            changed = cycle == 1 or bool(new_entries) or bool(closed_entries)

            if changed:
                os.system('cls' if os.name == 'nt' else 'clear')

                logger.info(f"Cycle #{cycle}  |  "
                      f"Min notional: ${min_notional:,.0f}  |  "
                      f"Asset: {asset or 'ALL'}  |  "
                      f"Refresh: {interval}s  |  "
                      f"Total qualifying: {len(positions)}")

                if new_entries and cycle > 1:
                    logger.info(f"{len(new_entries)} NEW position(s) entered the top {top}")
                if closed_entries and cycle > 1:
                    logger.info(f"{len(closed_entries)} position(s) dropped out")

                finder.print_results(top_positions)
                finder.print_concentration(concentration)
            else:
                logger.info(f"Cycle #{cycle}  |  No changes  |  "
                      f"{len(top_positions)} positions tracked  |  "
                      f"{len(positions)} saved to DB")

            prev_snapshot = current_snapshot
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        finder.close()


if __name__ == "__main__":
    main()
