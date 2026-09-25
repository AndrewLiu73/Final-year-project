import json
import os
import time
from pathlib import Path
from datetime import datetime
# from pymongo import MongoClient, UpdateOne
from dotenv import load_dotenv

from sqlite_db import get_connection, loads

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class LargeTradesFinder:

    def __init__(self, mongo_uri):
        # self.client = MongoClient(mongo_uri)
        # self.db = self.client['hyperliquid']
        self.db = get_connection()
        self.setup_indexes()

    def setup_indexes(self):
        # self.db["open_positions"].create_index(
        #     [("wallet_address", 1), ("asset", 1), ("direction", 1)], unique=True
        # )
        # self.db["open_positions"].create_index([("notional_usd", -1)])
        # self.db["open_positions"].create_index([("asset", 1)])
        # self.db["open_positions"].create_index([("direction", 1)])
        # self.db["open_positions"].create_index([("unrealized_pnl", -1)])
        # self.db["asset_concentration"].create_index("asset", unique=True)
        # self.db["asset_concentration"].create_index([("total_notional", -1)])
        pass  # indexes/unique constraints already declared in sqlite_db.SCHEMA_SQL (applied by get_connection())

    def _unwind_open_positions(self):
        """
        Mirrors the Mongo pipeline's {$match: not-bot, has-positions} + {$unwind: open_positions}
        step: yields (profitability_row_dict, position_dict) pairs with notional_usd added to
        each position, since open_positions only exists inside the JSON blob column.
        """
        cursor = self.db.execute(
            "SELECT wallet_address, account_value, total_pnl_usdc, win_rate_percentage, "
            "trade_count, last_updated, data FROM profitability_metrics "
            "WHERE open_positions_count > 0 AND (is_likely_bot IS NULL OR is_likely_bot = 0)"
        )
        for row in cursor.fetchall():
            doc = loads(row["data"])
            base = {
                "wallet_address": row["wallet_address"], "account_value": row["account_value"] or 0,
                "total_pnl_usdc": row["total_pnl_usdc"] or 0,
                "unrealized_pnl_usdc": doc.get("unrealized_pnl_usdc", 0),
                "win_rate_percentage": row["win_rate_percentage"] or 0,
                "trade_count": row["trade_count"] or 0, "last_updated": row["last_updated"],
            }
            for pos in doc.get("open_positions", []):
                pos = dict(pos)
                pos["notional_usd"] = pos.get("size", 0) * pos.get("entry_price", 0)
                yield base, pos

    def find_large_positions(self, min_notional_usd=10000, min_unrealized_pnl=None, asset=None):
        # pipeline = [
        #     {"$match": {"open_positions_count": {"$gt": 0}, "is_likely_bot": {"$ne": True}}},
        #     {"$unwind": "$open_positions"},
        #     {"$addFields": {"open_positions.notional_usd": {"$multiply": ["$open_positions.size", "$open_positions.entry_price"]}}}
        # ]
        #
        # position_match = {}
        # if min_notional_usd:
        #     position_match["open_positions.notional_usd"] = {"$gte": min_notional_usd}
        # if min_unrealized_pnl is not None:
        #     position_match["open_positions.unrealized_pnl"] = {"$gte": min_unrealized_pnl}
        # if asset:
        #     position_match["open_positions.asset"] = asset.upper()
        # if position_match:
        #     pipeline.append({"$match": position_match})
        #
        # pipeline.append({"$sort": {"open_positions.notional_usd": -1}})
        # pipeline.append({"$project": {
        #     "wallet_address": 1, "account_value": 1, "total_pnl_usdc": 1,
        #     "unrealized_pnl_usdc": 1, "win_rate_percentage": 1,
        #     "trade_count": 1, "last_updated": 1, "position": "$open_positions"
        # }})
        #
        # return list(self.db.profitability_metrics.aggregate(pipeline))

        results = []
        for base, pos in self._unwind_open_positions():
            if min_notional_usd and pos["notional_usd"] < min_notional_usd:
                continue
            if min_unrealized_pnl is not None and pos.get("unrealized_pnl", 0) < min_unrealized_pnl:
                continue
            if asset and pos.get("asset") != asset.upper():
                continue
            results.append({**base, "position": pos})

        results.sort(key=lambda r: r["position"]["notional_usd"], reverse=True)
        return results

    def save_positions(self, positions):
        now = datetime.now()
        # coll = self.db["open_positions"]
        ops, seen_keys = [], set()

        for p in positions:
            pos = p['position']
            key = {"wallet_address": p['wallet_address'], "asset": pos['asset'], "direction": pos['direction']}
            seen_keys.add((p['wallet_address'], pos['asset'], pos['direction']))
            doc = {**key, "size": pos['size'], "entry_price": pos['entry_price'],
                   "notional_usd": pos['notional_usd'], "unrealized_pnl": pos['unrealized_pnl'],
                   "account_value": p.get('account_value', 0), "total_pnl_usdc": p.get('total_pnl_usdc', 0),
                   "win_rate_percentage": p.get('win_rate_percentage', 0),
                   "trade_count": p.get('trade_count', 0), "last_updated": str(now)}
            # ops.append(UpdateOne(key, {"$set": doc}, upsert=True))
            ops.append(doc)

        # if ops:
        #     coll.bulk_write(ops, ordered=False)
        for doc in ops:
            self.db.execute(
                "INSERT INTO open_positions (wallet_address, asset, direction, notional_usd, unrealized_pnl, data) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(wallet_address, asset, direction) DO UPDATE SET "
                "notional_usd=excluded.notional_usd, unrealized_pnl=excluded.unrealized_pnl, data=excluded.data",
                (doc["wallet_address"], doc["asset"], doc["direction"],
                 doc["notional_usd"], doc["unrealized_pnl"], json.dumps(doc)),
            )
        self.db.commit()

        # stale_ids = [doc['_id'] for doc in coll.find({}, {"wallet_address": 1, "asset": 1, "direction": 1})
        #              if (doc['wallet_address'], doc['asset'], doc['direction']) not in seen_keys]
        # if stale_ids:
        #     coll.delete_many({"_id": {"$in": stale_ids}})
        # let SQLite do the diff instead of pulling every row into Python to compare by hand.
        seen_composite = [f"{w}|{a}|{d}" for (w, a, d) in seen_keys]
        if seen_composite:
            placeholders = ",".join("?" * len(seen_composite))
            self.db.execute(
                f"DELETE FROM open_positions WHERE (wallet_address || '|' || asset || '|' || direction) "
                f"NOT IN ({placeholders})",
                seen_composite,
            )
        else:
            self.db.execute("DELETE FROM open_positions")
        self.db.commit()

    def save_concentration(self, min_positions=3):
        # pipeline = [
        #     {"$match": {"open_positions_count": {"$gt": 0}, "is_likely_bot": {"$ne": True}}},
        #     {"$unwind": "$open_positions"},
        #     {"$addFields": {"open_positions.notional_usd": {"$multiply": ["$open_positions.size", "$open_positions.entry_price"]}}},
        #     {"$group": {
        #         "_id": "$open_positions.asset",
        #         "total_positions": {"$sum": 1},
        #         "total_notional": {"$sum": "$open_positions.notional_usd"},
        #         "total_unrealized_pnl": {"$sum": "$open_positions.unrealized_pnl"},
        #         "longs": {"$sum": {"$cond": [{"$eq": ["$open_positions.direction", "LONG"]}, 1, 0]}},
        #         "shorts": {"$sum": {"$cond": [{"$eq": ["$open_positions.direction", "SHORT"]}, 1, 0]}}
        #     }},
        #     {"$match": {"total_positions": {"$gte": min_positions}}},
        #     {"$sort": {"total_notional": -1}}
        # ]
        # results = list(self.db.profitability_metrics.aggregate(pipeline))

        groups = {}
        for _, pos in self._unwind_open_positions():
            asset = pos.get("asset")
            g = groups.setdefault(asset, {"_id": asset, "total_positions": 0, "total_notional": 0.0,
                                           "total_unrealized_pnl": 0.0, "longs": 0, "shorts": 0})
            g["total_positions"] += 1
            g["total_notional"] += pos["notional_usd"]
            g["total_unrealized_pnl"] += pos.get("unrealized_pnl", 0)
            if pos.get("direction") == "LONG": g["longs"] += 1
            elif pos.get("direction") == "SHORT": g["shorts"] += 1

        results = [g for g in groups.values() if g["total_positions"] >= min_positions]
        results.sort(key=lambda r: r["total_notional"], reverse=True)

        now = datetime.now()
        # coll = self.db["asset_concentration"]
        seen_assets, ops = set(), []

        for r in results:
            seen_assets.add(r['_id'])
            doc = {"asset": r['_id'], "total_positions": r['total_positions'],
                   "total_notional": r['total_notional'], "total_unrealized_pnl": r['total_unrealized_pnl'],
                   "longs": r['longs'], "shorts": r['shorts'], "last_updated": str(now)}
            # ops.append(UpdateOne({"asset": r['_id']}, {"$set": doc}, upsert=True))
            ops.append(doc)

        # if ops:
        #     coll.bulk_write(ops, ordered=False)
        # coll.delete_many({"asset": {"$nin": list(seen_assets)}})
        for doc in ops:
            self.db.execute(
                "INSERT INTO asset_concentration (asset, total_notional, data) VALUES (?, ?, ?) "
                "ON CONFLICT(asset) DO UPDATE SET total_notional=excluded.total_notional, data=excluded.data",
                (doc["asset"], doc["total_notional"], json.dumps(doc)),
            )
        if seen_assets:
            placeholders = ",".join("?" * len(seen_assets))
            self.db.execute(f"DELETE FROM asset_concentration WHERE asset NOT IN ({placeholders})", list(seen_assets))
        else:
            self.db.execute("DELETE FROM asset_concentration")
        self.db.commit()

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
        # self.client.close()
        self.db.close()


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
