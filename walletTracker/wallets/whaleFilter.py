import asyncio
import logging
from pathlib import Path
import motor.motor_asyncio
import pandas as pd

from hyperliquid.info import Info
from hyperliquid.utils import constants

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("MillionaireUserFilter")

# MongoDB connection details
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
USERS_COLLECTION = "users"
MILLIONAIRE_COLLECTION = "millionaires"

async def fetch_wallets_from_mongodb() -> list:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[USERS_COLLECTION]
    wallets = []
    async for doc in users_collection.find({}, {"_id": 0, "user": 1}):
        wallets.append(doc["user"])
    client.close()
    return wallets

def fetch_account_value(info: Info, wallet: str) -> float:
    """Fetch current account value using Hyperliquid SDK"""
    try:
        user_state = info.user_state(wallet)
        if user_state and 'marginSummary' in user_state:
            account_value = float(user_state['marginSummary']['accountValue'])
            logger.info(f"{wallet} account value: ${account_value:,.2f}")
            return account_value
        else:
            logger.warning(f"Could not retrieve account value for {wallet}")
            return 0.0
    except Exception as e:
        logger.error(f"Error fetching account value for {wallet}: {e}")
        return 0.0

async def filter_millionaire_users(
    min_balance: float = 1_000_000,
    testnet: bool = False
) -> list:
    wallets = await fetch_wallets_from_mongodb()
    logger.info(f"Loaded {len(wallets)} wallets from MongoDB")

    api_url = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    info = Info(api_url, skip_ws=True)
    millionaires = []

    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    millionaire_collection = db[MILLIONAIRE_COLLECTION]

    for idx, wallet in enumerate(wallets, start=1):
        logger.info(f"\n[{idx}/{len(wallets)}] Checking {wallet}")

        try:
            balance = fetch_account_value(info, wallet)
            if balance > min_balance:
                metrics = {'wallet': wallet, 'balance': balance}
                millionaires.append(metrics)
                logger.info(f"✅ {wallet} has account value ${balance:,.2f} - Added to millionaires list")

                await millionaire_collection.update_one(
                    {"wallet": wallet},
                    {"$set": metrics},
                    upsert=True
                )
            else:
                logger.info(f"❌ {wallet} balance below threshold")
        except Exception as e:
            logger.error(f"Error analyzing {wallet}: {e}")

        await asyncio.sleep(2)  # sleep between wallets (rate limit)

    client.close()
    return millionaires

async def main():
    users = await filter_millionaire_users(
        min_balance=1_000_000,
        testnet=False
    )
    if users:
        df = pd.DataFrame(users)
        output_csv = Path('data/millionaire_users.csv')
        output_csv.parent.mkdir(exist_ok=True)
        df.to_csv(output_csv, index=False)
        logger.info(f"\n✅ Found {len(users)} users with >$1M account value")
        logger.info(f"Detailed metrics saved to {output_csv}")
    else:
        logger.info("\n❌ No users met the balance criteria")

if __name__ == '__main__':
    asyncio.run(main())
