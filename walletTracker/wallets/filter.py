import asyncio
import aiohttp
import logging
import time
import numpy as np
from pathlib import Path
from typing import List, Dict
from collections import defaultdict
from datetime import datetime
import motor.motor_asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("ProfitableTraderFilter")

# MongoDB connection details
MONGO_URI = "mongodb+srv://andrewliu:xGMymy8wQ2vaL2No@cluster0.famk0m5.mongodb.net/hyperliquid?retryWrites=true&w=majority&authSource=admin"
DB_NAME = "hyperliquid"
COLLECTION_NAME = "users"

def get_api_url(testnet: bool = False) -> str:
    from hyperliquid.utils import constants
    base = constants.TESTNET_API_URL if testnet else constants.MAINNET_API_URL
    return f"{base}/info"

async def fetch_wallets_from_mongodb() -> List[str]:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    users_collection = db[COLLECTION_NAME]
    wallets = []
    async for doc in users_collection.find({}, {"_id": 0, "user": 1}):
        wallets.append(doc["user"])
    client.close()

    return wallets

async def fetch_all_fills(session: aiohttp.ClientSession, api_url: str, wallet: str) -> List[dict]:
    all_fills = []
    end_time = int(time.time() * 1000)
    start_time = 0
    retries = 0
    while True:
        payload = {
            "type": "userFillsByTime",
            "user": wallet,
            "startTime": start_time,
            "endTime": end_time
        }
        try:
            async with session.post(api_url, json=payload) as resp:
                if resp.status == 429:
                    logger.warning(f"Rate limited on {wallet}. Sleeping for longer...")
                    await asyncio.sleep(5)
                    retries += 1
                    if retries > 5:
                        logger.error(f"Too many rate limits on {wallet}, moving to next.")
                        break
                    continue
                resp.raise_for_status()
                fills = await resp.json()
        except Exception as e:
            logger.error(f"Error fetching fills for {wallet}: {e}")
            break
        if not fills:
            break
        all_fills.extend(fills)
        retries = 0  # Reset after success
        if len(fills) == 2000:
            oldest_time = min(fill['time'] for fill in fills)
            end_time = oldest_time - 1
        else:
            break
        await asyncio.sleep(2)  # sleep longer between paginated calls
    return all_fills

def calculate_trader_metrics(fills: List[dict]) -> Dict:
    if not fills:
        return None
    closing_trades = []
    daily_pnl = defaultdict(float)
    for fill in fills:
        closed_pnl = float(fill.get('closedPnl', '0'))
        fee = float(fill.get('fee', '0'))
        timestamp = fill.get('time', 0)
        if abs(closed_pnl - fee) > 0.0001:
            closing_trades.append(closed_pnl)
            day = datetime.fromtimestamp(timestamp / 1000).date()
            daily_pnl[day] += closed_pnl
    if not closing_trades:
        return None
    total_pnl = sum(closing_trades)
    winning_trades = [pnl for pnl in closing_trades if pnl > 0]
    losing_trades = [pnl for pnl in closing_trades if pnl < 0]
    total_trades = len(closing_trades)
    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
    total_wins = sum(winning_trades) if winning_trades else 0
    total_losses = abs(sum(losing_trades)) if losing_trades else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
    daily_pnl_values = list(daily_pnl.values())
    consistency = np.std(daily_pnl_values) if len(daily_pnl_values) > 1 else 0
    cumulative_pnl = np.cumsum(closing_trades)
    running_max = np.maximum.accumulate(cumulative_pnl)
    drawdown = cumulative_pnl - running_max
    max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0
    risk_adjusted_return = abs(total_pnl / max_drawdown) if max_drawdown != 0 else float('inf')
    return {
        'total_pnl': total_pnl,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'consistency_std': consistency,
        'max_drawdown': max_drawdown,
        'risk_adjusted_return': risk_adjusted_return,
        'avg_pnl_per_trade': total_pnl / total_trades if total_trades > 0 else 0
    }

async def analyze_trader(session: aiohttp.ClientSession, api_url: str, wallet: str) -> Dict:
    logger.info(f"Analyzing wallet: {wallet}")
    fills = await fetch_all_fills(session, api_url, wallet)
    if not fills:
        logger.warning(f"No fills found for {wallet}")
        return None
    metrics = calculate_trader_metrics(fills)
    if metrics:
        metrics['wallet'] = wallet
        logger.info(f"✓ {wallet}: PnL=${metrics['total_pnl']:.2f}, "
                    f"WinRate={metrics['win_rate']*100:.1f}%, "
                    f"PF={metrics['profit_factor']:.2f}, "
                    f"MaxDD=${metrics['max_drawdown']:.2f}")
    return metrics

async def fetch_account_balance(session: aiohttp.ClientSession, api_url: str, wallet: str) -> float:
    payload = {"type": "userState", "user": wallet}
    try:
        async with session.post(api_url, json=payload) as resp:
            if resp.status == 429:
                logger.warning(f"Rate limited fetching balance for {wallet}. Sleeping...")
                await asyncio.sleep(5)
                return 0.0  # Skip balance if rate limited
            resp.raise_for_status()
            data = await resp.json()
            balance = float(data.get('marginSummary', {}).get('accountValue', 0.0))
            return balance
    except Exception as e:
        logger.error(f"Error fetching account balance for {wallet}: {e}")
        return 0.0

async def filter_profitable_traders(
    min_pnl: float = 1000.0,
    min_win_rate: float = 0.45,
    min_profit_factor: float = 1.2,
    max_consistency_std: float = 5000.0,
    min_risk_adjusted: float = 2.0,
    testnet: bool = False
) -> List[Dict]:
    wallets = await fetch_wallets_from_mongodb()
    logger.info(f"Loaded {len(wallets)} wallets from MongoDB")

    api_url = get_api_url(testnet)
    profitable_traders = []

    output_file = Path('data/profitable_traders.txt')
    output_file.parent.mkdir(exist_ok=True)
    if output_file.exists():
        existing_wallets = set(line.split(',')[0] for line in output_file.read_text().splitlines())
    else:
        existing_wallets = set()

    async with aiohttp.ClientSession() as session:
        for idx, wallet in enumerate(wallets, start=1):
            logger.info(f"\n[{idx}/{len(wallets)}] Checking {wallet}")

            try:
                metrics = await analyze_trader(session, api_url, wallet)
                if metrics is None:
                    continue
                if (metrics['total_pnl'] >= min_pnl and
                        metrics['win_rate'] >= min_win_rate and
                        metrics['profit_factor'] >= min_profit_factor and
                        metrics['consistency_std'] <= max_consistency_std and
                        metrics['risk_adjusted_return'] >= min_risk_adjusted):

                    balance = await fetch_account_balance(session, api_url, wallet)
                    metrics['balance'] = balance

                    profitable_traders.append(metrics)
                    logger.info(f"✅ PASSED ALL FILTERS - Balance: ${balance:.2f} - Added to profitable traders list")

                    with output_file.open('a', encoding='utf-8') as f:
                        if wallet not in existing_wallets:
                            f.write(
                                f"{wallet},{balance},{metrics['total_pnl']},{metrics['win_rate']},{metrics['profit_factor']},{metrics['max_drawdown']}\n")
                            existing_wallets.add(wallet)
                else:
                    logger.info(f"❌ Did not meet filter criteria")

            except Exception as e:
                logger.error(f"Error analyzing {wallet}: {e}")

            await asyncio.sleep(2)  # sleep between wallets (rate limit)

    return profitable_traders

async def main():
    traders = await filter_profitable_traders(
        min_pnl=1000.0,
        min_win_rate=0.45,
        min_profit_factor=1.2,
        max_consistency_std=5000.0,
        min_risk_adjusted=2.0,
        testnet=False
    )
    if traders:
        import pandas as pd
        df = pd.DataFrame(traders)
        output_csv = Path('data/profitable_traders_metrics.csv')
        df.to_csv(output_csv, index=False)
        logger.info(f"\n✅ Found {len(traders)} profitable traders")
        logger.info(f"Detailed metrics saved to {output_csv}")
    else:
        logger.info("\n❌ No traders met all profitability criteria")

if __name__ == '__main__':
    asyncio.run(main())
