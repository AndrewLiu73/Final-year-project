import asyncio
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import httpx

load_dotenv()

MONGO_URI        = os.getenv("MONGO_URI")
DB_NAME          = os.getenv("DB_NAME", "hyperliquid")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
HL_API           = "https://api.hyperliquid.xyz/info"

async def send_telegram(message, chat_id):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=data)
        print(f"Telegram response: {res.status_code}")

async def fetch_positions_realtime(wallets):
    payload = {
        "type": "batchClearinghouseStates",
        "users": wallets
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(HL_API, json=payload, timeout=10)
        res.raise_for_status()
        return res.json()

async def test_bias_logic(db, chat_id):
    print(f"\n--- Test: Real-time bias from Hyperliquid API ---")
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

    batch_data = await fetch_positions_realtime(wallets)

    long_val  = 0.0
    short_val = 0.0

    for i, state in enumerate(batch_data):
        wallet = wallets[i]
        positions = state.get("assetPositions", [])
        print(f"\nWallet {wallet[:10]}... -> {len(positions)} positions")

        for item in positions:
            pos     = item.get("position", {})
            coin    = pos.get("coin", "?")
            szi     = float(pos.get("szi", 0))        # positive = long, negative = short
            entry   = float(pos.get("entryPx", 0))
            notional = abs(szi) * entry

            if szi > 0:
                long_val  += notional
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
    db      = client[DB_NAME]

    await test_bias_logic(db, chat_id)

    client.close()
    print("\nDone.")

if __name__ == "__main__":
    asyncio.run(main())
