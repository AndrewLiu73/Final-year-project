import asyncio
import os
from pathlib import Path
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import httpx

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MONGO_URI      = os.getenv("MONGO_URI")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
HL_API         = "https://api.hyperliquid.xyz/info"


async def send_telegram(message, chat_id):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=data)
        print(f"Telegram response: {res.status_code}")


async def fetch_wallet_positions(client, wallet):
    payload = {"type": "clearinghouseState", "user": wallet}
    try:
        res = await client.post(HL_API, json=payload, timeout=10)
        res.raise_for_status()
        return wallet, res.json()
    except Exception as e:
        print(f"Failed for wallet {wallet[:10]}: {e}")
        return wallet, None


async def fetch_positions_realtime(wallets):
    async with httpx.AsyncClient() as client:
        tasks   = [fetch_wallet_positions(client, w) for w in wallets]
        results = await asyncio.gather(*tasks)
    return results


async def bias_logic(db, chat_id):
    print(f"\n--- Real-time bias from Hyperliquid API ---")
    watchlist_col = db["watchlists"]
    users_col     = db["users"]

    user = await users_col.find_one({"telegram_id": str(chat_id)})
    if not user:
        print(f"No user found with telegram_id {chat_id}")
        return

    print(f"Found user: {user.get('user_id')}")

    watchlist_items = await watchlist_col.find(
        {"user_id": user["user_id"]}, {"wallet_address": 1}
    ).to_list(length=500)

    wallets = [item["wallet_address"] for item in watchlist_items]
    print(f"Wallets in watchlist: {len(wallets)}")

    if not wallets:
        print("Watchlist is empty")
        return

    results = await fetch_positions_realtime(wallets)

    long_val  = 0.0
    short_val = 0.0

    for wallet, state in results:
        if state is None:
            continue

        positions = state.get("assetPositions", [])
        print(f"\nWallet {wallet[:10]}... -> {len(positions)} positions")

        for item in positions:
            pos      = item.get("position", {})
            coin     = pos.get("coin", "?")
            szi      = float(pos.get("szi", 0))
            entry    = float(pos.get("entryPx", 0))
            notional = abs(szi) * entry

            if szi > 0:
                long_val += notional
                print(f"  LONG  {coin}: size={szi} entry={entry} notional={notional:.2f}")
            elif szi < 0:
                short_val += notional
                print(f"  SHORT {coin}: size={szi} entry={entry} notional={notional:.2f}")

    total = long_val + short_val
    if total == 0:
        print("\nNo open positions found across all wallets")
        return

    long_pct     = (long_val  / total) * 100
    short_pct    = (short_val / total) * 100
    current_side = "LONG" if long_pct > 50 else "SHORT"

    print(f"\nLong:  {long_pct:.1f}%")
    print(f"Short: {short_pct:.1f}%")
    print(f"Bias:  {current_side}")

    emoji   = "🟢" if current_side == "LONG" else "🔴"
    message = (
        f"{emoji} <b>Watchlist Bias Alert</b>\n\n"
        f"Current bias: <b>{current_side}</b>\n"
        f"Long: {long_pct:.1f}%  |  Short: {short_pct:.1f}%\n"
        f"Wallets tracked: {len(wallets)}\n"
        f"Time: {datetime.now().strftime('%H:%M %d/%m/%Y')}"
    )
    await send_telegram(message, chat_id=str(chat_id))


async def main():
    chat_id = input("Enter your Telegram chat ID: ").strip()
    client  = AsyncIOMotorClient(MONGO_URI)
    db      = client["hyperliquid"]

    await bias_logic(db, chat_id)

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
