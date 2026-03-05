from pymongo import MongoClient

MONGO_URI="mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"

db = MONGO_URI["users"]

result = db.users.update_many(
    {},
    {
        "$unset": {
            "last_seen": "",
            "tx_count": "",
            "has_trading_activity": "",
            "is_profitable": "",
            "last_profitability_check": "",
            "total_pnl": "",
            "trade_count": "",
            "win_rate": ""
        }
    }
)

print(f"Matched: {result.matched_count}, Modified: {result.modified_count}")

client.close()
