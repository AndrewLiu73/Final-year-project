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


    def __init__(self, mongoUri):
        self.client = MongoClient(mongoUri)
        self.db = self.client['hyperliquid']
        self.setupIndexes()

    def setupIndexes(self):
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

    def findLargePositions(self, minNotionalUsd=10000, minUnrealizedPnl=None, asset=None):
        """
        Find users with large open positions.

        Args:
            minNotionalUsd: Minimum position size in USD (entry_price * size)
            minUnrealizedPnl: Minimum unrealized PnL (can be negative to find big losses)
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
        positionMatch = {}

        if minNotionalUsd:
            positionMatch["open_positions.notional_usd"] = {"$gte": minNotionalUsd}

        if minUnrealizedPnl is not None:
            positionMatch["open_positions.unrealized_pnl"] = {"$gte": minUnrealizedPnl}

        if asset:
            positionMatch["open_positions.asset"] = asset.upper()

        if positionMatch:
            pipeline.append({"$match": positionMatch})

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

    def savePositions(self, positions):
        """
        Upsert positions into the open_positions collection.
        Key = wallet_address + asset + direction so each position is one document.
        Positions that no longer qualify get removed.
        """
        now = datetime.now()
        coll = self.db["open_positions"]

        # build bulk upserts
        ops = []
        seenKeys = set()
        for p in positions:
            pos = p['position']
            key = {
                "wallet_address": p['wallet_address'],
                "asset": pos['asset'],
                "direction": pos['direction'],
            }
            seenKeys.add((p['wallet_address'], pos['asset'], pos['direction']))

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
        allDocs = coll.find({}, {"wallet_address": 1, "asset": 1, "direction": 1})
        staleIds = []
        for doc in allDocs:
            k = (doc['wallet_address'], doc['asset'], doc['direction'])
            if k not in seenKeys:
                staleIds.append(doc['_id'])

        if staleIds:
            coll.delete_many({"_id": {"$in": staleIds}})
            logger.info(f"removed {len(staleIds)} closed/stale positions")

    def saveConcentration(self, minPositions=3):
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
            {"$match": {"total_positions": {"$gte": minPositions}}},
            {"$sort": {"total_notional": -1}}
        ]

        results = list(self.db.profitability_metrics.aggregate(pipeline))
        now = datetime.now()
        coll = self.db["asset_concentration"]

        seenAssets = set()
        ops = []
        for r in results:
            asset = r['_id']
            seenAssets.add(asset)
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
        coll.delete_many({"asset": {"$nin": list(seenAssets)}})

        return results

    def printResults(self, positions):
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
            pnlStr = f"${pnl:,.2f}"
            if pnl > 0:
                pnlIndicator = "[+]"
            elif pnl < 0:
                pnlIndicator = "[-]"
            else:
                pnlIndicator = "[=]"

            print(f"#{i:3d} | {pos['asset']:8s} | {pos['direction']:5s} | ${notional:15,.2f}")
            print(f"      Wallet: {p['wallet_address']}")
            print(f"      Position: {pos['size']:,.4f} @ ${pos['entry_price']:,.2f}")
            print(f"      Unrealized PnL: {pnlIndicator} {pnlStr}")
            print(f"      Account Value: ${p.get('account_value', 0):,.2f} | "
                  f"Win Rate: {p.get('win_rate_percentage', 0):.1f}% | "
                  f"Trades: {p.get('trade_count', 0):,}")

            lastUpdated = p.get('last_updated')
            if lastUpdated:
                if isinstance(lastUpdated, str):
                    print(f"      Last Updated: {lastUpdated}")
                else:
                    print(f"      Last Updated: {lastUpdated.strftime('%Y-%m-%d %H:%M:%S')}")

            print("-" * 120)

        # Summary stats
        totalNotional = sum(p['position']['notional_usd'] for p in positions)
        totalUpnl = sum(p['position']['unrealized_pnl'] for p in positions)

        print(f"\nSummary:")
        print(f"  Total Positions Shown: {len(positions)}")
        print(f"  Total Notional: ${totalNotional:,.2f}")
        print(f"  Total Unrealized PnL: ${totalUpnl:,.2f}")
        print("=" * 120)

    def printConcentration(self, results):
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
            lsRatio = f"{longs}/{shorts}"

            print(f"{asset:<10} {positions:>10,} ${notional:>18,.2f} ${upnl:>18,.2f}  {lsRatio}")

        print("=" * 100)

    def close(self):
        self.client.close()


def main():
    minNotional = 10000
    asset = None
    top = 20
    interval = 60

    mongoUri = os.getenv('MONGO_URI')
    if not mongoUri:
        print("Error: MONGO_URI not found in environment variables")
        return

    finder = LargeTradesFinder(mongoUri)

    # track previous cycle to detect changes
    prevSnapshot = set()

    try:
        cycle = 0
        while True:
            cycle += 1

            positions = finder.findLargePositions(
                minNotionalUsd=minNotional,
                asset=asset,
            )

            # save ALL qualifying positions to MongoDB (upsert)
            finder.savePositions(positions)
            concentration = finder.saveConcentration(minPositions=3)

            # build a snapshot of the current top positions so we can detect changes
            topPositions = positions[:top]
            currentSnapshot = set()
            for p in topPositions:
                pos = p['position']
                currentSnapshot.add((p['wallet_address'], pos['asset'], pos['direction']))

            # on first run always print, after that only print when something changed
            newEntries = currentSnapshot - prevSnapshot
            closedEntries = prevSnapshot - currentSnapshot
            changed = cycle == 1 or bool(newEntries) or bool(closedEntries)

            if changed:
                os.system('cls' if os.name == 'nt' else 'clear')

                logger.info(f"Cycle #{cycle}  |  "
                      f"Min notional: ${minNotional:,.0f}  |  "
                      f"Asset: {asset or 'ALL'}  |  "
                      f"Refresh: {interval}s  |  "
                      f"Total qualifying: {len(positions)}")

                if newEntries and cycle > 1:
                    logger.info(f"{len(newEntries)} NEW position(s) entered the top {top}")
                if closedEntries and cycle > 1:
                    logger.info(f"{len(closedEntries)} position(s) dropped out")

                finder.printResults(topPositions)
                finder.printConcentration(concentration)
            else:
                logger.info(f"Cycle #{cycle}  |  No changes  |  "
                      f"{len(topPositions)} positions tracked  |  "
                      f"{len(positions)} saved to DB")

            prevSnapshot = currentSnapshot
            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        finder.close()


if __name__ == "__main__":
    main()
