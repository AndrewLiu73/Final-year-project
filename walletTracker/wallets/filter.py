import asyncio
import aiohttp
import logging
from pathlib import Path
from typing import List

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("BTCTraderFilter")

# Hyperliquid REST endpoint for user fills
def get_api_url(testnet: bool = False) -> str:
    from hyperliquid.utils import constants
    base = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    return f"{base}/info"

async def has_btc_trade(session: aiohttp.ClientSession, api_url: str, wallet: str) -> bool:
    """
    Check if the given wallet has any fills involving BTC (e.g., BTC-PERP) via REST.
    Returns True if any fill's coin field contains 'BTC'.
    """
    payload = {"type": "userFills", "user": wallet, "startTime": 0}
    try:
        async with session.post(api_url, json=payload) as resp:
            resp.raise_for_status()
            fills = await resp.json()
    except Exception as e:
        logger.error(f"Error fetching fills for {wallet}: {e}")
        return False

    for fill in fills:
        coin = fill.get('coin', '')
        # Match any coin containing 'BTC'
        if 'BTC' in coin.upper():
            return True
    return False

OUTPUT_FILE = Path('btc_traders.txt')  # file to append BTC traders

async def filter_btc_traders(address_file: Path, testnet: bool = False) -> List[str]:
    """
    Read wallets from a file, check each for any BTC fills,
    and return list of wallets that have traded BTC.
    """
    if not address_file.exists():
        logger.error(f"Address file not found: {address_file}")
        return []
    wallets = [line.strip() for line in address_file.read_text().splitlines() if line.strip()]
    logger.info(f"Loaded {len(wallets)} wallets from {address_file}")
    api_url = get_api_url(testnet)
    traders: List[str] = []
    async with aiohttp.ClientSession() as session:
        for idx, w in enumerate(wallets, start=1):
            logger.info(f"Checking {idx}/{len(wallets)}: {w}")
            try:
                traded = await has_btc_trade(session, api_url, w)
                if traded:
                    traders.append(w)
                    logger.info(f"✓ Wallet {w} has traded BTC")
                    # Append immediately to output file
                    OUTPUT_FILE.parent.mkdir(exist_ok=True)
                    with OUTPUT_FILE.open('a', encoding='utf-8') as f:
                        f.write(w + "\n")  # append newline

                else:
                    logger.info(f"✗ Wallet {w} has not traded BTC")
            except aiohttp.ClientResponseError as e:
                if e.status == 429:
                    logger.warning(f"Rate limited on {w}, retrying after 1s")
                    await asyncio.sleep(1)
                    # retry once
                    try:
                        if await has_btc_trade(session, api_url, w):
                            traders.append(w)
                            logger.info(f"✓ Wallet {w} has traded BTC (retry)")
                    except Exception:
                        pass
                else:
                    logger.error(f"Error checking fills for {w}: {e}")
            await asyncio.sleep(0.01)
    return traders

async def main():
    address_file = Path('filtered_eth_addresses.txt')
    traders = await filter_btc_traders(address_file, testnet=False)
    if not traders:
        logger.info("No wallets found that traded BTC.")
    else:
        output_file = Path('btc_traders.txt')
        output_file.write_text("\n".join(traders) + "\n")
        logger.info(f"Wrote {len(traders)} BTC trading wallets to {output_file}")

if __name__ == '__main__':
    asyncio.run(main())
