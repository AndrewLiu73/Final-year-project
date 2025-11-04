import aiohttp
import asyncio
from collections import Counter, defaultdict
from motor.motor_asyncio import AsyncIOMotorClient

# --- Settings ---
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
MILLIONAIRE_COLLECTION = "users"
HYPERLIQUID_API = "https://api.hyperliquid.xyz/info"
TARGET_COINS = ["BTC", "ETH","HYPE"]
MAX_RETRIES = 3

PARALLEL = 5          # Parallel requests (safe given HL rate limits)
RATE_LIMIT_DELAY = 0.10  # 0.1s between batches (extra buffer, can be tweaked lower/higher)

# --- Wallet fetching from MongoDB millionaires ---
async def fetch_millionaires_wallets():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    millionaires_coll = db[MILLIONAIRE_COLLECTION]
    docs = await millionaires_coll.find({}, {"_id": 0, "user": 1}).to_list(None)
    return [d["user"] for d in docs if "user" in d]


# --- Position Fetch: Resilient, single-wallet ---
async def fetch_positions(session, wallet):
    for attempt in range(MAX_RETRIES):
        try:
            async with session.post(
                HYPERLIQUID_API,
                json={"type": "clearinghouseState", "user": wallet}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("assetPositions", [])
                elif resp.status == 422:
                    print(f"[{wallet}] ❌ Wallet not supported or invalid (422)")
                    return []
                else:
                    print(f"[{wallet}] Error: {resp.status}")
        except Exception as e:
            print(f"[{wallet}] Exception: {e}")

        wait_time = 2 ** attempt
        print(f"[{wallet}] Retry {attempt+1}/{MAX_RETRIES} in {wait_time}s...")
        await asyncio.sleep(wait_time)
    print(f"[{wallet}] ⚠️ Failed after {MAX_RETRIES} attempts.")
    return []

# --- Parallel batch position fetch ---
async def fetch_all_positions(wallets, session, parallel=PARALLEL):
    sema = asyncio.Semaphore(parallel)
    async def worker(wallet):
        async with sema:
            positions = await fetch_positions(session, wallet)
            return wallet, positions
    tasks = [worker(w) for w in wallets]
    results = await asyncio.gather(*tasks)
    return dict(results)

# --- Bias Calculation ---
def update_bias_summary(total_bias_qty, total_bias_val, positions):
    for pos_data in positions:
        pos = pos_data.get("position", {})
        coin = pos.get("coin")
        szi = float(pos.get("szi", 0))
        val = float(pos.get("positionValue", 0))
        if szi == 0 or val == 0:
            continue
        side = "B" if szi > 0 else "A"
        if coin in TARGET_COINS:
            total_bias_qty[coin][side] += abs(szi)
            total_bias_val[coin][side] += val

def print_bias_summary(total_bias_qty, total_bias_val):
    print("\n===== Millionaire Directional Bias Summary =====")
    for coin in TARGET_COINS:
        long_sz = total_bias_qty[coin].get("B", 0.0)
        short_sz = total_bias_qty[coin].get("A", 0.0)
        total_sz = long_sz + short_sz

        long_val = total_bias_val[coin].get("B", 0.0)
        short_val = total_bias_val[coin].get("A", 0.0)
        total_val = long_val + short_val

        long_pct = (long_val / total_val * 100) if total_val > 0 else 0
        short_pct = (short_val / total_val * 100) if total_val > 0 else 0
        direction = (
            "Long" if long_val > short_val
            else "Short" if short_val > long_val
            else "Neutral"
        )
        print(f"{coin} Bias → {direction}")
        print(f"    Size     → Long: {long_sz:.4f} | Short: {short_sz:.4f}")
        print(f"    Position → Long: ${long_val:.2f} ({long_pct:.1f}%) | Short: ${short_val:.2f} ({short_pct:.1f}%)")
    print("==============================================\n")

# --- Main watcher: reacts to collection change events ---
async def millionaire_watcher():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    coll = db[MILLIONAIRE_COLLECTION]

    print("Fetching initial set of millionaire wallets and positions...")
    wallets = await fetch_millionaires_wallets()

    async with aiohttp.ClientSession() as session:
        # PARALLEL INITIAL FETCH
        wallet_positions = await fetch_all_positions(wallets, session, parallel=PARALLEL)
        bias_qty = {coin: Counter() for coin in TARGET_COINS}
        bias_val = {coin: Counter() for coin in TARGET_COINS}
        for wallet, positions in wallet_positions.items():
            update_bias_summary(bias_qty, bias_val, positions)
        print_bias_summary(bias_qty, bias_val)

        # Now react to live MongoDB events, always using PARALLEL
        async with coll.watch([{'$match': {'operationType': {'$in': ['insert', 'update']}}}]) as stream:
            print("Watching for new millionaire positions...")
            async for change in stream:
                wallet = (change.get('fullDocument') or {}).get('wallet')
                if not wallet:
                    continue
                print(f"\n[ALERT] Millionaire wallet '{wallet}' inserted/updated. Checking open positions...")
                # Rebuild full bias summary after a new/updated millionaire
                wallets = await fetch_millionaires_wallets()
                wallet_positions = await fetch_all_positions(wallets, session, parallel=PARALLEL)
                bias_qty = {coin: Counter() for coin in TARGET_COINS}
                bias_val = {coin: Counter() for coin in TARGET_COINS}
                for w, positions in wallet_positions.items():
                    update_bias_summary(bias_qty, bias_val, positions)
                print_bias_summary(bias_qty, bias_val)

# --- Main entry point ---
async def main():
    await millionaire_watcher()

if __name__ == "__main__":
    asyncio.run(main())
