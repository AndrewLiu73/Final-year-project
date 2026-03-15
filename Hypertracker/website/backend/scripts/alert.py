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
POLL_INTERVAL  = 30

last_bias_per_user = {}
known_positions    = {}


async def send_telegram(message, telegram_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": telegram_id, "text": message, "parse_mode": "HTML"}
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json=data)
        if res.status_code != 200:
            print(f"telegram failed: {res.status_code}")


async def fetch_wallet(client, wallet):
    try:
        res = await client.post(HL_API, json={"type": "clearinghouseState", "user": wallet}, timeout=10)
        res.raise_for_status()
        return wallet, res.json()
    except Exception as e:
        print(f"failed to fetch {wallet[:10]}: {e}")
        return wallet, None


async def fetch_all(wallets):
    async with httpx.AsyncClient() as client:
        return await asyncio.gather(*[fetch_wallet(client, w) for w in wallets])


def parse_positions(results):
    current_map = {}
    long_val = 0.0
    short_val = 0.0

    for wallet, state in results:
        if not state:
            continue
        current_map[wallet] = {}
        for item in state.get("assetPositions", []):
            pos = item.get("position", {})
            coin = pos.get("coin", "?")
            szi = float(pos.get("szi", 0))
            entry = float(pos.get("entryPx", 0) or 0)
            notional = abs(szi) * entry
            side = "LONG" if szi > 0 else "SHORT" if szi < 0 else None

            if not side:
                continue

            current_map[wallet][coin] = {
                "szi":       szi,
                "entry":     entry,
                "notional":  notional,
                "side":      side,
                "upnl":      float(pos.get("unrealizedPnl", 0) or 0),
                "liq_price": float(pos.get("liquidationPx", 0) or 0),
            }

            if szi > 0:
                long_val += notional
            else:
                short_val += notional

    return current_map, long_val, short_val


def now_str():
    return datetime.now().strftime("%H:%M %d/%m/%Y")


def build_positions_message(current_map, long_val, short_val):
    total = long_val + short_val
    long_pct  = (long_val  / total * 100) if total else 0
    short_pct = (short_val / total * 100) if total else 0
    bias  = "LONG" if long_pct >= 50 else "SHORT"
    emoji = "🟢" if bias == "LONG" else "🔴"

    coin_agg = {}
    for wallet, coins in current_map.items():
        for coin, d in coins.items():
            if coin not in coin_agg:
                coin_agg[coin] = {"long_notional": 0, "short_notional": 0, "long_count": 0, "short_count": 0, "upnl": 0}
            coin_agg[coin]["upnl"] += d["upnl"]
            if d["side"] == "LONG":
                coin_agg[coin]["long_notional"] += d["notional"]
                coin_agg[coin]["long_count"] += 1
            else:
                coin_agg[coin]["short_notional"] += d["notional"]
                coin_agg[coin]["short_count"] += 1

    lines = [
        "📋 <b>HyperTracker — Open Positions</b>",
        f"Time: {now_str()}",
        "",
        f"{emoji} Bias: <b>{bias}</b>  |  Long: {long_pct:.1f}%  Short: {short_pct:.1f}%",
        f"Total: ${total:,.0f}  |  Long: ${long_val:,.0f}  Short: ${short_val:,.0f}",
        "",
    ]

    if coin_agg:
        lines.append("─── <b>By Asset</b> ───")
        for coin, agg in sorted(coin_agg.items(), key=lambda x: -(x[1]["long_notional"] + x[1]["short_notional"])):
            coin_total = agg["long_notional"] + agg["short_notional"]
            upnl_str = f"  uPnL: {'+'if agg['upnl'] >= 0 else ''}{agg['upnl']:,.0f}" if agg["upnl"] != 0 else ""
            l_part = f"🟢 L×{agg['long_count']} ${agg['long_notional']:,.0f}" if agg["long_count"] else ""
            s_part = f"🔴 S×{agg['short_count']} ${agg['short_notional']:,.0f}" if agg["short_count"] else ""
            parts = "  ".join(filter(None, [l_part, s_part]))
            lines.append(f"  <b>{coin}</b>  ${coin_total:,.0f}{upnl_str}")
            lines.append(f"    {parts}")
        lines.append("")

    active = {w: c for w, c in current_map.items() if c}
    if active:
        lines.append("─── <b>By Wallet</b> ───")
        for wallet, coins in active.items():
            w_long  = sum(d["notional"] for d in coins.values() if d["side"] == "LONG")
            w_short = sum(d["notional"] for d in coins.values() if d["side"] == "SHORT")
            w_upnl  = sum(d["upnl"] for d in coins.values())
            sign    = "+" if w_upnl >= 0 else ""
            lines.append(f"<b>{wallet[:8]}...{wallet[-4:]}</b>  ({len(coins)} pos  uPnL: {sign}{w_upnl:,.0f})")
            for coin, d in sorted(coins.items()):
                e    = "🟢" if d["side"] == "LONG" else "🔴"
                sign = "+" if d["upnl"] >= 0 else ""
                liq  = f"  liq: ${d['liq_price']:,.2f}" if d["liq_price"] else ""
                lines.append(
                    f"  {e} {coin}  {d['side']}  sz={d['szi']}  "
                    f"entry=${d['entry']:,.2f}  notional=${d['notional']:,.0f}  "
                    f"uPnL:{sign}{d['upnl']:,.0f}{liq}"
                )
            lines.append("")
    else:
        lines.append("no open positions found")

    return "\n".join(lines)


async def send_snapshot(results, wallets, telegram_id):
    current_map, long_val, short_val = parse_positions(results)
    msg = build_positions_message(current_map, long_val, short_val)
    msg = msg.replace("📋 <b>HyperTracker — Open Positions</b>", "📊 <b>HyperTracker — Live Snapshot</b>")
    msg += f"\nWallets tracked: {len(wallets)}"
    await send_telegram(msg, telegram_id)
    bias = "LONG" if long_val >= short_val else "SHORT"
    return current_map, bias


async def detect_trades(user_id, current_map, telegram_id):
    prev_map = known_positions.get(user_id, {})
    alerts = []

    for wallet, coins in current_map.items():
        prev = prev_map.get(wallet, {})

        for coin, d in coins.items():
            if coin not in prev:
                e    = "🟢" if d["side"] == "LONG" else "🔴"
                sign = "+" if d["upnl"] >= 0 else ""
                liq  = f"\nLiq: ${d['liq_price']:,.2f}" if d["liq_price"] else ""
                alerts.append(
                    f"{e} <b>New Trade Opened</b>\n"
                    f"Wallet: {wallet[:8]}...{wallet[-4:]}\n"
                    f"Coin: <b>{coin}</b>  |  Side: <b>{d['side']}</b>\n"
                    f"Size: {d['szi']}  |  Entry: ${d['entry']:,.2f}\n"
                    f"Notional: ${d['notional']:,.0f}  uPnL: {sign}{d['upnl']:,.2f}"
                    f"{liq}\nTime: {now_str()}"
                )

            elif prev[coin]["side"] != d["side"]:
                e = "🟢" if d["side"] == "LONG" else "🔴"
                alerts.append(
                    f"🔄 <b>Position Flipped</b>\n"
                    f"Wallet: {wallet[:8]}...{wallet[-4:]}\n"
                    f"Coin: <b>{coin}</b>  {prev[coin]['side']} → <b>{d['side']}</b>\n"
                    f"Size: {d['szi']}  |  Entry: ${d['entry']:,.2f}\n"
                    f"Time: {now_str()}"
                )

            elif abs(d["szi"]) != abs(prev[coin]["szi"]):
                diff = abs(d["szi"]) - abs(prev[coin]["szi"])
                label = "📈 Scaled IN" if diff > 0 else "📉 Scaled OUT"
                e = "🟢" if d["side"] == "LONG" else "🔴"
                alerts.append(
                    f"{e} <b>{label}</b>\n"
                    f"Wallet: {wallet[:8]}...{wallet[-4:]}\n"
                    f"Coin: <b>{coin}</b>  ({d['side']})\n"
                    f"Size: {prev[coin]['szi']} → {d['szi']}  (Δ{diff:+.4f})\n"
                    f"Entry: ${d['entry']:,.2f}  Notional: ${d['notional']:,.0f}\n"
                    f"Time: {now_str()}"
                )

        for coin in prev:
            if coin not in coins:
                alerts.append(
                    f"⚪ <b>Position Closed</b>\n"
                    f"Wallet: {wallet[:8]}...{wallet[-4:]}\n"
                    f"Coin: <b>{coin}</b>  ({prev[coin]['side']})\n"
                    f"Was: sz={prev[coin]['szi']}  entry=${prev[coin]['entry']:,.2f}\n"
                    f"Time: {now_str()}"
                )

    for alert in alerts:
        await send_telegram(alert, telegram_id)

    known_positions[user_id] = current_map


async def detect_bias(user_id, long_val, short_val, telegram_id):
    total     = long_val + short_val
    long_pct  = (long_val  / total * 100) if total else 0
    short_pct = (short_val / total * 100) if total else 0
    bias  = "LONG" if long_pct >= 50 else "SHORT"
    prev  = last_bias_per_user.get(user_id)

    if prev and bias != prev:
        emoji = "🟢" if bias == "LONG" else "🔴"
        await send_telegram(
            f"⚠️ <b>Bias Shift!</b>\n\n"
            f"{prev} → {emoji} <b>{bias}</b>\n"
            f"Long: {long_pct:.1f}%  (${long_val:,.0f})\n"
            f"Short: {short_pct:.1f}%  (${short_val:,.0f})\n"
            f"Time: {now_str()}",
            telegram_id
        )

    last_bias_per_user[user_id] = bias
    return bias


SUMMARY_EVERY = 10

async def monitor_user(db, user_id, telegram_id):
    watchlist = await db["watchlists"].find(
        {"user_id": user_id}, {"wallet_address": 1}
    ).to_list(length=500)
    wallets = [item["wallet_address"] for item in watchlist]

    if not wallets:
        print(f"user {user_id} has empty watchlist, skipping")
        return

    print(f"monitoring {len(wallets)} wallets for user {user_id}")

    results = await fetch_all(wallets)
    current_map, bias = await send_snapshot(results, wallets, telegram_id)
    known_positions[user_id]    = current_map
    last_bias_per_user[user_id] = bias

    poll_count = 0
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        poll_count += 1

        results = await fetch_all(wallets)
        current_map, long_val, short_val = parse_positions(results)

        await detect_trades(user_id, current_map, telegram_id)
        bias = await detect_bias(user_id, long_val, short_val, telegram_id)

        if poll_count % SUMMARY_EVERY == 0:
            msg = build_positions_message(current_map, long_val, short_val)
            await send_telegram(msg, telegram_id)

        total_open = sum(len(c) for c in current_map.values())
        print(f"[{now_str()}] user {user_id} | bias={bias} L=${long_val:,.0f} S=${short_val:,.0f} open={total_open}")


async def main():
    mongo = AsyncIOMotorClient(MONGO_URI)
    db = mongo["hyperliquid"]

    users = await db["users"].find(
        {"telegram_id": {"$exists": True, "$ne": ""}},
        {"user_id": 1, "telegram_id": 1}
    ).to_list(length=1000)

    if not users:
        print("no users with telegram ids found, they need to save their id on the watchlist page")
        mongo.close()
        return

    print(f"starting monitor for {len(users)} users")

    tasks = [
        asyncio.create_task(monitor_user(db, u["user_id"], u["telegram_id"]))
        for u in users
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        print("stopped")
    finally:
        mongo.close()


if __name__ == "__main__":
    asyncio.run(main())
