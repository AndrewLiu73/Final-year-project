import asyncio
import aiohttp
import os
import logging
from dataclasses import dataclass
from typing import Dict
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# --- Data classes ---
@dataclass
class Position:
    coin: str
    size: float
    entry_price: float
    side: str  # 'long' or 'short'
    unrealized_pnl: float

# --- Copy trader ---
class HyperliquidCopyTrader:
    def __init__(self, target_wallet: str, private_key: str, wallet_address: str, copy_ratio: float = 1.0):
        self.target_wallet = target_wallet.lower()
        self.private_key = private_key
        self.wallet_address = wallet_address.lower()
        self.copy_ratio = copy_ratio

        # SDK clients
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = Exchange(private_key, constants.MAINNET_API_URL, account_address=wallet_address)

        self.processed_trades = set()
        self.session = None

        # logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    # --- REST helper to get positions ---
    async def get_user_state(self) -> Dict:
        """Fetch raw clearinghouse state for the target wallet."""
        url = f"{constants.MAINNET_API_URL.replace('https', 'http')}/info"
        payload = {"type": "clearinghouseState", "user": self.target_wallet}
        async with self.session.post(url, json=payload) as resp:
            resp.raise_for_status()
            return await resp.json()

    def parse_positions(self, user_state: Dict) -> Dict[str, Position]:
        """Extract non‐zero positions into Position objects."""
        positions = {}
        for pos_data in user_state.get("assetPositions", []):
            p = pos_data.get("position", {})
            size = float(p.get("szi", 0))
            if size == 0:
                continue
            coin = p.get("coin")
            positions[coin] = Position(
                coin=coin,
                size=abs(size),
                entry_price=float(p.get("entryPx", 0)),
                side="long" if size > 0 else "short",
                unrealized_pnl=float(p.get("unrealizedPnl", 0))
            )
        return positions

    async def display_target_status(self):
        """Print whether the target is currently in any trade, and list them."""
        state = await self.get_user_state()
        positions = self.parse_positions(state)
        if positions:
            self.logger.info(f"🔍 Target is IN a trade: {len(positions)} position(s) open")
            for pos in positions.values():
                self.logger.info(f"  • {pos.coin}: {pos.side} {pos.size} @ {pos.entry_price:.4f} (PnL {pos.unrealized_pnl:.2f})")
        else:
            self.logger.info("🔍 Target is NOT in any trade right now.")

    # --- Exact‐price order placement ---
    async def place_order_exact(self, coin: str, side: str, size: float, limit_price: float) -> bool:
        try:
            is_buy = side.lower() == "buy"
            res = self.exchange.order(coin, is_buy, abs(size), limit_price, {"limit": {"tif": "Ioc"}})
            if res and res.get("status") == "ok":
                self.logger.info(f"✅ Placed {side.upper()} {size} {coin} @ {limit_price}")
                return True
            self.logger.error(f"❌ Order failed: {res}")
            return False
        except Exception as e:
            self.logger.error(f"❌ Error placing exact order: {e}")
            return False

    # --- WebSocket watcher ---
    async def watch_and_copy_fills(self):
        ws_url = "wss://api.hyperliquid.xyz/ws"
        async with self.session.ws_connect(ws_url) as ws:
            await ws.send_json({
                "method": "subscribe",
                "subscription": {"type": "userFills", "user": self.target_wallet}
            })
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                data = msg.json()
                # skip control messages
                if data.get("subscription", {}).get("type") != "userFills":
                    continue

                fill = data.get("data", {})
                tx = fill.get("tx_hash")
                if not tx or tx in self.processed_trades:
                    continue
                self.processed_trades.add(tx)

                coin = fill.get("coin")
                side = "buy" if fill.get("side") == "long" else "sell"
                raw_size = float(fill.get("sz", 0))
                size = raw_size * self.copy_ratio
                price = float(fill.get("px", 0))

                self.logger.info(f"📈 Detected target {side.upper()} {raw_size} {coin} @ {price}; copying {size}")
                await self.place_order_exact(coin, side, size, price)

    # --- Main loop ---
    async def run_forever(self):
        async with aiohttp.ClientSession() as session:
            self.session = session
            # 1) Show initial status
            await self.display_target_status()
            # 2) Start copying fills
            self.logger.info(f"▶️ Starting fill‐copy loop (ratio={self.copy_ratio})…")
            await self.watch_and_copy_fills()

# --- Entrypoint ---
async def main():
    target = "0x224b1f69f1dcf8b3671d3760f37bdd115e4696c4"
    key    = "0xb18e6ddf122866b80251f933b2a2e59c71e44a60b8fc5cd50539d82b6776f08a"
    addr   = "0xB12D02f32C69a834bb245F38dDa6Cc391C4855Ee"
    ratio  =  1.0

    if not (target and key and addr):
        print("Please set TARGET_WALLET, HYPERLIQUID_PRIVATE_KEY, and YOUR_WALLET_ADDRESS")
        return

    trader = HyperliquidCopyTrader(target, key, addr, ratio)
    await trader.run_forever()

if __name__ == "__main__":
    asyncio.run(main())
