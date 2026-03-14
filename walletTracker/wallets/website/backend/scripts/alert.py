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


async def sendTelegram(message, chatId):
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chatId, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=data)
        print(f"Telegram response: {res.status_code}")


async def fetchWalletPositions(client, wallet):
    payload = {"type": "clearinghouseState", "user": wallet}
    try:
        res = await client.post(HL_API, json=payload, timeout=10)
        res.raise_for_status()
        return wallet, res.json()
    except Exception as e:
        print(f"Failed for wallet {wallet[:10]}: {e}")
        return wallet, None


async def fetchPositionsRealtime(wallets):
    async with httpx.AsyncClient() as client:
        tasks   = [fetchWalletPositions(client, w) for w in wallets]
        results = await asyncio.gather(*tasks)
    return results


async def biasLogic(db, chatId):
    print(f"\n--- Real-time bias from Hyperliquid API ---")
    watchlistCol = db["watchlists"]
    usersCol     = db["users"]

    user = await usersCol.find_one({"telegram_id": str(chatId)})
    if not user:
        print(f"No user found with telegram_id {chatId}")
        return

    print(f"Found user: {user.get('user_id')}")

    watchlistItems = await watchlistCol.find(
        {"user_id": user["user_id"]}, {"wallet_address": 1}
    ).to_list(length=500)

    wallets = [item["wallet_address"] for item in watchlistItems]
    print(f"Wallets in watchlist: {len(wallets)}")

    if not wallets:
        print("Watchlist is empty")
        return

    results = await fetchPositionsRealtime(wallets)

    longVal  = 0.0
    shortVal = 0.0

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
                longVal += notional
                print(f"  LONG  {coin}: size={szi} entry={entry} notional={notional:.2f}")
            elif szi < 0:
                shortVal += notional
                print(f"  SHORT {coin}: size={szi} entry={entry} notional={notional:.2f}")

    total = longVal + shortVal
    if total == 0:
        print("\nNo open positions found across all wallets")
        return

    longPct     = (longVal  / total) * 100
    shortPct    = (shortVal / total) * 100
    currentSide = "LONG" if longPct > 50 else "SHORT"

    print(f"\nLong:  {longPct:.1f}%")
    print(f"Short: {shortPct:.1f}%")
    print(f"Bias:  {currentSide}")

    emoji   = "🟢" if currentSide == "LONG" else "🔴"
    message = (
        f"{emoji} <b>Watchlist Bias Alert</b>\n\n"
        f"Current bias: <b>{currentSide}</b>\n"
        f"Long: {longPct:.1f}%  |  Short: {shortPct:.1f}%\n"
        f"Wallets tracked: {len(wallets)}\n"
        f"Time: {datetime.now().strftime('%H:%M %d/%m/%Y')}"
    )
    await sendTelegram(message, chatId=str(chatId))


async def main():
    chatId = input("Enter your Telegram chat ID: ").strip()
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client["hyperliquid"]

    await biasLogic(db, chatId)

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
