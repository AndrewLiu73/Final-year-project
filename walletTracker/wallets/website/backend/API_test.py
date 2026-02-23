import requests
import json
import os
import time
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

BASE_URL   = "https://api.hyperliquid.xyz/info"
DELAY      = 1.5   # slightly more conservative than 1.2
MAX_RETRY  = 3


def post(payload, retries=MAX_RETRY):
    for attempt in range(retries):
        try:
            resp = requests.post(BASE_URL, json=payload, timeout=10)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code == 429:
                wait = (attempt + 1) * 3  # 3s, 6s, 9s backoff
                print(f"  429 rate limited on {payload.get('type')} - waiting {wait}s (attempt {attempt + 1}/{retries})")
                time.sleep(wait)
                continue

            if resp.status_code == 422:
                # wallet has no data for this endpoint - not an error
                return None

            print(f"  HTTP {resp.status_code} for type={payload.get('type')}")
            return None

        except Exception as e:
            print(f"  request error: {e}")
            return None

    print(f"  gave up on {payload.get('type')} after {retries} attempts")
    return None


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def debug_wallet_unrealized_pnl(wallet_address):
    section(f"WALLET: {wallet_address}")

    # ----------------------------------------------------------------
    # 1. clearinghouseState - account value, margin, open positions
    # ----------------------------------------------------------------
    section("1. clearinghouseState")
    data = post({"type": "clearinghouseState", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))

        margin = data.get('marginSummary', {})
        print(f"\n  marginSummary keys: {list(margin.keys())}")

        asset_positions = data.get('assetPositions', [])
        print(f"  open positions: {len(asset_positions)}")

        total_unrealized = 0
        for idx, pos in enumerate(asset_positions):
            pos_data = pos.get('position', {})
            coin     = pos_data.get('coin', 'UNKNOWN')
            size     = float(pos_data.get('szi', 0))
            upnl     = pos_data.get('unrealizedPnl')

            if size == 0:
                continue

            print(f"\n  position {idx + 1}: {coin}")
            print(f"    size:          {size}")
            print(f"    entry_px:      {pos_data.get('entryPx')}")
            print(f"    unrealizedPnl: {upnl}")

            if upnl is not None:
                total_unrealized += float(upnl)

        print(f"\n  total unrealized PnL (summed from positions): ${total_unrealized:.2f}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 2. portfolio - all-time realized PnL, volume, PnL history
    # ----------------------------------------------------------------
    section("2. portfolio")
    data = post({"type": "portfolio", "user": wallet_address})

    if data:
        for period, stats in data:
            print(f"\n  period: {period}")
            if isinstance(stats, dict):
                print(f"    vlm (volume): {stats.get('vlm')}")
                pnl_hist = stats.get('pnlHistory', [])
                if pnl_hist:
                    print(f"    latest realized PnL: {pnl_hist[-1][1]}")
                    print(f"    pnlHistory entries:  {len(pnl_hist)}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 3. openOrders
    # ----------------------------------------------------------------
    section("3. openOrders")
    data = post({"type": "openOrders", "user": wallet_address})

    if data is not None:
        print(f"  open orders count: {len(data)}")
        if data:
            print(f"  first order: {json.dumps(data[0], indent=2)}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 4. frontendOpenOrders
    # ----------------------------------------------------------------
    section("4. frontendOpenOrders")
    data = post({"type": "frontendOpenOrders", "user": wallet_address})

    if data is not None:
        print(f"  frontend open orders count: {len(data)}")
        if data:
            print(f"  first order keys: {list(data[0].keys())}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 5. userFills
    # ----------------------------------------------------------------
    section("5. userFills (latest batch)")
    data = post({"type": "userFills", "user": wallet_address})

    if data is not None:
        print(f"  fills returned: {len(data)}")
        if data:
            print(f"  first fill keys: {list(data[0].keys())}")
            print(f"  first fill:      {json.dumps(data[0], indent=2)}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 6. userFillsByTime (last 7 days)
    # ----------------------------------------------------------------
    section("6. userFillsByTime (last 7 days)")
    now_ms  = int(time.time() * 1000)
    week_ms = 7 * 24 * 60 * 60 * 1000
    data = post({
        "type":      "userFillsByTime",
        "user":      wallet_address,
        "startTime": now_ms - week_ms,
        "endTime":   now_ms
    })

    if data is not None:
        print(f"  fills in last 7 days: {len(data)}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 7. historicalOrders
    # ----------------------------------------------------------------
    section("7. historicalOrders")
    data = post({"type": "historicalOrders", "user": wallet_address})

    if data is not None:
        print(f"  historical orders count: {len(data)}")
        if data:
            print(f"  first order keys: {list(data[0].keys())}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 8. userFees
    # ----------------------------------------------------------------
    section("8. userFees")
    data = post({"type": "userFees", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 9. userRateLimit
    # ----------------------------------------------------------------
    section("9. userRateLimit")
    data = post({"type": "userRateLimit", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 10. subAccounts - extra sleep before this one to avoid 429
    # ----------------------------------------------------------------
    section("10. subAccounts")
    time.sleep(3)  # buffer - this endpoint is more sensitive to burst
    data = post({"type": "subAccounts", "user": wallet_address})

    if data is not None:
        print(f"  sub-accounts: {len(data)}")
        if data:
            print(json.dumps(data[0], indent=2))
    else:
        print("  no sub-accounts (or none linked)")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 11. userVaultEquities
    # ----------------------------------------------------------------
    section("11. userVaultEquities")
    data = post({"type": "userVaultEquities", "user": wallet_address})

    if data is not None:
        print(f"  vault positions: {len(data)}")
        if data:
            print(json.dumps(data[0], indent=2))

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 12. userRole - subAccount, master, vault leader, etc
    # ----------------------------------------------------------------
    section("12. userRole")
    data = post({"type": "userRole", "user": wallet_address})

    if data:
        role = data.get('role', 'unknown')
        print(f"  role: {role}")

        role_data = data.get('data', {})
        if role == 'subAccount' and role_data:
            print(f"  master wallet: {role_data.get('master')}")
        elif role == 'vaultLeader' and role_data:
            print(f"  vault address: {role_data.get('vault')}")

        print(f"\n  full response: {json.dumps(data, indent=2)}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 13. referral
    # ----------------------------------------------------------------
    section("13. referral")
    data = post({"type": "referral", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 14. spotClearinghouseState
    # ----------------------------------------------------------------
    section("14. spotClearinghouseState")
    data = post({"type": "spotClearinghouseState", "user": wallet_address})

    if data:
        balances = data.get('balances', [])
        print(f"  spot token balances: {len(balances)}")
        for b in balances:
            print(f"    {b.get('coin')}: {b.get('total')}")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 15. twapSliceFills - 422 means wallet never used TWAP, skip silently
    # ----------------------------------------------------------------
    section("15. twapSliceFills")
    data = post({"type": "twapSliceFills", "user": wallet_address})

    if data is not None:
        print(f"  twap slice fills: {len(data)}")
    else:
        print("  no TWAP fills (wallet has not used TWAP orders)")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 16. stakingSummary - 422 means wallet has not staked HYPE
    # ----------------------------------------------------------------
    section("16. stakingSummary")
    data = post({"type": "stakingSummary", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))
    else:
        print("  no staking data (wallet has not staked HYPE)")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 17. delegations
    # ----------------------------------------------------------------
    section("17. delegations")
    data = post({"type": "delegations", "user": wallet_address})

    if data is not None:
        print(f"  delegations: {len(data)}")
        if data:
            print(json.dumps(data[0], indent=2))
    else:
        print("  no delegations")

    time.sleep(DELAY)

    # ----------------------------------------------------------------
    # 18. stakingRewards - 422 means wallet has not staked HYPE
    # ----------------------------------------------------------------
    section("18. stakingRewards")
    data = post({"type": "stakingRewards", "user": wallet_address})

    if data:
        print(json.dumps(data, indent=2))
    else:
        print("  no staking rewards (wallet has not staked HYPE)")

    time.sleep(DELAY)


def check_database_sample():
    section("CHECKING DATABASE")

    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("  MONGO_URI not found in .env")
        return

    try:
        client = MongoClient(mongo_uri)
        db     = client['hyperliquid']

        total          = db.profitability_metrics.count_documents({})
        with_positions = db.profitability_metrics.count_documents({"open_positions_count": {"$gt": 0}})
        zero_upnl      = db.profitability_metrics.count_documents({
            "open_positions_count": {"$gt": 0},
            "unrealized_pnl_usdc": 0
        })

        print(f"  total records:           {total}")
        print(f"  records with positions:  {with_positions}")
        print(f"  positions but zero upnl: {zero_upnl}")

        if zero_upnl > 0:
            pct = round(zero_upnl / with_positions * 100, 1)
            print(f"  ({pct}% of wallets with positions have stale zero upnl - will be fixed on next scan cycle)")

        sample = db.profitability_metrics.find_one({"open_positions_count": {"$gt": 0}})

        if sample:
            print(f"\n  sample wallet:     {sample.get('wallet_address')}")
            print(f"  unrealized PnL:    {sample.get('unrealized_pnl_usdc')}")
            print(f"  realized PnL:      {sample.get('realized_pnl_usdc')}")
            print(f"  total PnL:         {sample.get('total_pnl_usdc')}")
            print(f"  open positions:    {sample.get('open_positions_count')}")
            for pos in sample.get('open_positions', []):
                print(f"    - {pos}")

        client.close()

    except Exception as e:
        print(f"  database error: {e}")


if __name__ == "__main__":
    test_wallet = "0x6ba2ad09aa6629a423b59b71f3564d84ce66c001"

    debug_wallet_unrealized_pnl(test_wallet)
    check_database_sample()
