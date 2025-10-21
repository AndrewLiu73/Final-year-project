import motor.motor_asyncio
import asyncio
import pandas as pd

MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
MILLIONAIRES_COLLECTION = "millionaires"

async def export_wallets_and_balances():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    collection = db[MILLIONAIRES_COLLECTION]

    data = []
    async for doc in collection.find({}, {"_id": 0, "wallet": 1, "balance": 1}):
        data.append(doc)

    if data:
        df = pd.DataFrame(data)
        df.to_csv('wallets_balances.csv', index=False)
        print(f"Exported {len(data)} wallet and balance entries to wallets_balances.csv")
    else:
        print("No data found.")

    client.close()

if __name__ == "__main__":
    asyncio.run(export_wallets_and_balances())
