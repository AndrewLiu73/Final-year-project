import os
import time
from pathlib import Path
from datetime import datetime
from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class LargeTradesFinder:

    def __init__(self, mongo_uri):
        self.client = MongoClient(mongo_uri)
        self.db = self.client['hyperliquid']
        self.setup_indexes()

    def setup_indexes(self):
        self.db["open_positions"].create_index(
            [("wallet_address", 1), ("asset", 1), ("direction", 1)], unique=True
        )
        self.db["open_positions"].create_index([("notional_usd", -1)])
        self.db["open_positions"].create_index([("asset", 1)])
        self.db["open_positions"].create_index([("direction", 1)])
        self.db["open_positions"].create_index([("unrealized_pnl", -1)])
        self.db["asset_concentration"].create_index("asset", unique=True)
        self.db["asset_concentration"].create_index([("total_notional", -1)])

    def find_large_positions(self, min_notional_usd=10000, min_unrealized_pnl=None, asset=None):
        pipeline = [
            {"$match": {"open_positions_count": {"$gt": 0}, "is_likely_bot": {"$ne": True}}},
            {"$unwind": "$open_positions"},
            {"$addFields": {"open_positions.notional_usd": {"$multiply": ["$open_positions.size", "$open_positions.entry_price"]}}}
        ]

        position_match = {}
        if min_notional_usd:
            position_match["open_positions.notional_usd"] = {"$gte": min_notional_usd}
        if min_unrealized_pnl is not None:
            position_match["open_positions.unrealized_pnl"] = {"$gte": min_unrealized_pnl}
        if asset:
            position_match["open_positions.asset"] = asset.upper()
        if position_match:
            pipeline.append({"$match": position_match})

        pipeline.append({"$sort": {"open_positions.notional_usd": -1}})
        pipeline.append({"$project": {
            "wallet_address": 1, "account_value": 1, "total_pnl_usdc": 1,
            "unrealized_pnl_usdc": 1, "win_rate_percentage": 1,
            "trade_count": 1, "last_updated": 1, "position": "$open_positions"
        }})

        return list(self.db.profitability_metrics.aggregate(pipeline))

    def save_positions(self, positions):
        now = datetime.now()
        coll = self.db["open_positions"]
        ops, seen_keys = [], set()

        for p in positions:
            pos = p['position']
            key = {"wallet_address": p['wallet_address'], "asset": pos['asset'], "direction": pos['direction']}
            seen_keys.add((p['wallet_address'], pos['asset'], pos['direction']))
            ops.append(UpdateOne(key, {"$set": {**key, "size": pos['size'], "entry_price": pos['entry_price'],
                "notional_usd": pos['notional_usd'], "unrealized_pnl": pos['unrealized_pnl'],
                "account_value": p.get('account_value', 0), "total_pnl_usdc": p.get('total_pnl_usdc', 0),
                "win_rate_percentage": p.get('win_rate_percentage', 0),
                "trade_count": p.get('trade_count', 0), "last_updated": now}}, upsert=True))

        if ops:
            coll.bulk_write(ops, ordered=False)

        stale_ids = [doc['_id'] for doc in coll.find({}, {"wallet_address": 1, "asset": 1, "direction": 1})
                     if (doc['wallet_address'], doc['asset'], doc['direction']) not in seen_keys]
        if stale_ids:
            coll.delete_many({"_id": {"$in": stale_ids}})

    def save_concentration(self, min_positions=3):
        pipeline = [
            {"$match": {"open_positions_count": {"$gt": 0}, "is_likely_bot": {"$ne": True}}},
            {"$unwind": "$open_positions"},
            {"$addFields": {"open_positions.notional_usd": {"$multiply": ["$open_positions.size", "$open_positions.entry_price"]}}},
            {"$group": {
                "_id": "$open_positions.asset",
                "total_positions": {"$sum": 1},
                "total_notional": {"$sum": "$open_positions.notional_usd"},
                "total_unrealized_pnl": {"$sum": "$open_positions.unrealized_pnl"},
                "longs": {"$sum": {"$cond": [{"$eq": ["$open_positions.direction", "LONG"]}, 1, 0]}},
                "shorts": {"$sum": {"$cond": [{"$eq": ["$open_positions.direction", "SHORT"]}, 1, 0]}}
            }},
            {"$match": {"total_positions": {"$gte": min_positions}}},
            {"$sort": {"total_notional": -1}}
        ]

        results = list(self.db.profitability_metrics.aggregate(pipeline))
        now = datetime.now()
        coll = self.db["asset_concentration"]
        seen_assets, ops = set(), []

        for r in results:
            seen_assets.add(r['_id'])
            ops.append(UpdateOne({"asset": r['_id']}, {"$set": {
                "asset": r['_id'], "total_positions": r['total_positions'],
                "total_notional": r['total_notional'], "total_unrealized_pnl": r['total_unrealized_pnl'],
                "longs": r['longs'], "shorts": r['shorts'], "last_updated": now}}, upsert=True))

        if ops:
            coll.bulk_write(ops, ordered=False)
        coll.delete_many({"asset": {"$nin": list(seen_assets)}})

        return results

    def print_results(self, positions):
        for i, p in enumerate(positions, 1):
            pos = p['position']
            pnl = pos['unrealized_pnl']
            print(f"#{i:3d} {pos['asset']:8s} {pos['direction']:5s} ${pos['notional_usd']:>15,.2f} "
                  f"uPnL: {'[+]' if pnl > 0 else '[-]' if pnl < 0 else '[=]'} ${pnl:,.2f} "
                  f"| {p['wallet_address']}")

    def print_concentration(self, results):
        print(f"\n{'Asset':<10} {'Pos':>6} {'Notional':>20} {'uPnL':>18} {'L/S'}")
        for r in results:
            print(f"{r['_id']:<10} {r['total_positions']:>6,} ${r['total_notional']:>18,.2f} "
                  f"${r['total_unrealized_pnl']:>17,.2f} {r['longs']}/{r['shorts']}")

    def close(self):
        self.client.close()


def main():
    min_notional, asset, top, interval = 10000, None, 20, 60
    finder = LargeTradesFinder(os.getenv('MONGO_URI'))
    prev_snapshot, cycle = set(), 0

    while True:
        cycle += 1
        positions = finder.find_large_positions(min_notional_usd=min_notional, asset=asset)
        finder.save_positions(positions)
        concentration = finder.save_concentration(min_positions=3)

        top_positions = positions[:top]
        current_snapshot = {(p['wallet_address'], p['position']['asset'], p['position']['direction']) for p in top_positions}

        if cycle == 1 or current_snapshot != prev_snapshot:
            os.system('cls' if os.name == 'nt' else 'clear')
            finder.print_results(top_positions)
            finder.print_concentration(concentration)

        prev_snapshot = current_snapshot
        time.sleep(interval)


if __name__ == "__main__":
    main()
