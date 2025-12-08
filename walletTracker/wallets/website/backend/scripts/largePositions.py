import logging
from hyperliquid.info import Info
from hyperliquid.utils import constants

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("HL_WalletOpenPositions")

info = Info(constants.MAINNET_API_URL, skip_ws=True)

def get_user_open_positions(wallet, min_size_usd=1_000_000):
    logger.info(f"Checking open positions for wallet: {wallet}")
    payload = {"type": "userState", "user": wallet}
    try:
        user_state = info.raw_request(payload)
        positions = []
        assets = user_state.get("assetPositions", [])
        for pos in assets:
            if pos["type"] != "oneWay":
                continue
            position_data = pos["position"]
            size = float(position_data.get("szi", 0))
            entry_px = float(position_data.get("entryPx", 0))
            notional = size * entry_px
            if notional >= min_size_usd:
                positions.append({
                    "coin": position_data["coin"],
                    "size": size,
                    "entryPx": entry_px,
                    "notional": notional
                })
        return positions
    except Exception as e:
        logger.error(f"Error fetching open positions for {wallet}: {e}")
        return []


def report_open_positions(wallet, positions):
    for pos in positions:
        print(f"Wallet: {wallet}\n  Coin: {pos['coin']}\n  Size: {pos['size']}\n  EntryPx: {pos['entryPx']}\n  Notional: ${pos['notional']:.2f}\n{'-'*35}")

if __name__ == "__main__":
    # Read wallets from users.txt
    with open("../../../data/users.txt") as f:
        track_list = [line.strip() for line in f if line.strip()]
    min_size_usd = 1_000_000  # $1M threshold

    for wallet in track_list:
        positions = get_user_open_positions(wallet, min_size_usd=min_size_usd)
        if positions:
            report_open_positions(wallet, positions)
        else:
            logger.info(f"No open positions >= ${min_size_usd:,} for wallet: {wallet}")
