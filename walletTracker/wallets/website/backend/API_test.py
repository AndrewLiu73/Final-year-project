import requests
import json
import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()


def debug_wallet_unrealized_pnl(wallet_address):
    """Test script to see actual API response structure"""

    print(f"\n{'=' * 60}")
    print(f"Testing wallet: {wallet_address}")
    print(f"{'=' * 60}\n")

    # Get clearinghouse state
    try:
        response = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "clearinghouseState", "user": wallet_address},
            timeout=10
        )

        print(f"Status Code: {response.status_code}")

        if response.status_code != 200:
            print(f"ERROR: HTTP {response.status_code}")
            return

        data = response.json()

        print("\n=== FULL API RESPONSE ===")
        print(json.dumps(data, indent=2))

        print("\n=== CHECKING FOR UNREALIZED PNL ===")

        # Check assetPositions structure
        asset_positions = data.get('assetPositions', [])
        print(f"Number of asset positions: {len(asset_positions)}")

        if not asset_positions:
            print("❌ No positions found - wallet might have no open trades")
            return

        print("\n--- First Position Full Structure ---")
        first_pos = asset_positions[0]
        print(json.dumps(first_pos, indent=2))

        # Check nested position data
        position_data = first_pos.get('position', {})
        print("\n--- Position Data Keys ---")
        print(list(position_data.keys()))

        # Look for unrealized PnL
        unrealized_pnl = position_data.get('unrealizedPnl')
        print(f"\n🔍 Unrealized PnL Value: {unrealized_pnl}")
        print(f"   Type: {type(unrealized_pnl)}")

        if unrealized_pnl is None:
            print("⚠️  WARNING: 'unrealizedPnl' key not found!")
            print(f"   Available keys: {list(position_data.keys())}")

        # Check all positions
        print("\n=== ALL POSITIONS ANALYSIS ===")
        total_unrealized = 0
        positions_with_pnl = 0

        for idx, pos in enumerate(asset_positions):
            pos_data = pos.get('position', {})
            coin = pos_data.get('coin', 'UNKNOWN')
            size = float(pos_data.get('szi', 0))
            entry_px = pos_data.get('entryPx', 0)
            upnl = pos_data.get('unrealizedPnl')

            print(f"\n📊 Position {idx + 1}: {coin}")
            print(f"   Size (szi): {size}")
            print(f"   Entry Price: {entry_px}")
            print(f"   Unrealized PnL: {upnl}")

            if size == 0:
                print(f"   ⏭️  Skipped (size = 0)")
                continue

            if upnl is None:
                print(f"   ❌ ERROR: unrealizedPnl is None/missing!")
            else:
                try:
                    upnl_float = float(upnl)
                    total_unrealized += upnl_float
                    positions_with_pnl += 1
                    print(f"   ✅ Added {upnl_float:.2f} to total")
                except (ValueError, TypeError) as e:
                    print(f"   ❌ ERROR: Could not convert '{upnl}' to float: {e}")

        print(f"\n{'=' * 60}")
        print(f"SUMMARY:")
        print(f"  Total Positions: {len(asset_positions)}")
        print(f"  Positions with PnL: {positions_with_pnl}")
        print(f"  Total Unrealized PnL: ${total_unrealized:.2f}")
        print(f"{'=' * 60}\n")

    except Exception as e:
        print(f"❌ Exception: {e}")
        import traceback
        traceback.print_exc()


def check_database_sample():
    """Check what's in the database"""
    print("\n=== CHECKING DATABASE ===\n")

    mongo_uri = os.getenv('MONGO_URI')
    if not mongo_uri:
        print("❌ MONGO_URI not found in .env")
        return

    try:
        client = MongoClient(mongo_uri)
        db = client['hyperliquid']

        # Count total records
        total = db.profitability_metrics.count_documents({})
        print(f"Total records in profitability_metrics: {total}")

        # Count records with positions
        with_positions = db.profitability_metrics.count_documents({"open_positions_count": {"$gt": 0}})
        print(f"Records with open positions: {with_positions}")

        # Get sample with positions
        sample = db.profitability_metrics.find_one({"open_positions_count": {"$gt": 0}})

        if sample:
            print("\n--- Sample Record with Positions ---")
            print(f"Wallet: {sample.get('wallet_address')}")
            print(f"Unrealized PnL: {sample.get('unrealized_pnl_usdc')}")
            print(f"Realized PnL: {sample.get('realized_pnl_usdc')}")
            print(f"Total PnL: {sample.get('total_pnl_usdc')}")
            print(f"Open Positions Count: {sample.get('open_positions_count')}")
            print(f"\nOpen Positions:")
            for pos in sample.get('open_positions', []):
                print(f"  - {pos}")
        else:
            print("❌ No records with open positions found in database")

        # Check records with zero unrealized PnL but have positions
        zero_upnl = db.profitability_metrics.count_documents({
            "open_positions_count": {"$gt": 0},
            "unrealized_pnl_usdc": 0
        })
        print(f"\n⚠️  Records with positions but ZERO unrealized PnL: {zero_upnl}")

        if zero_upnl > 0:
            print("   This indicates the API extraction issue!")

        client.close()

    except Exception as e:
        print(f"❌ Database error: {e}")


if __name__ == "__main__":
    # Test with your example wallet
    test_wallet = "0x6ba2ad09aa6629a423b59b71f3564d84ce66c001"

    print("🔍 TESTING API EXTRACTION")
    debug_wallet_unrealized_pnl(test_wallet)

    print("\n" + "=" * 60)
    print("🔍 CHECKING DATABASE")
    check_database_sample()
