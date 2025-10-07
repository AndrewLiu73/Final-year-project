import asyncio
import requests
from datetime import datetime, timezone

# Endpoints
GATEIO_URL = "https://fx-api.gateio.ws/api/v4/futures/usdt/tickers"
BITGET_URL = "https://api.bitget.com/api/v2/mix/market/open-interest"
HYPER_URL  = "https://api.hyperliquid.xyz/info"

async def run_oi_loop():
    while True:
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # Binance: number of contracts
        try:
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest",
                params={"symbol": "BTCUSDT"},
                timeout=5
            )
            resp.raise_for_status()
            binance_oi = float(resp.json().get("openInterest", 0.0))
        except Exception:
            binance_oi = None

        # OKX: BTC exposure in coin units (oiCcy)
        try:
            resp = requests.get(
                "https://www.okx.com/api/v5/public/open-interest",
                params={"instType": "SWAP", "instId": "BTC-USDT-SWAP"},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            okx_oi = float(data[0].get("oiCcy", 0.0)) if data else None
        except Exception:
            okx_oi = None

        # Bybit: live BTC exposure (openInterest field) — unchanged
        try:
            y = requests.get(
                "https://api.bybit.com/v5/market/open-interest",
                params={
                    "category": "linear",
                    "symbol": "BTCUSDT",
                    "intervalTime": "5min",
                    "limit": 1
                }
            ).json().get('result', {})
            lst = y.get('list', [])
            bybit_oi = float(lst[0]['openInterest']) if lst else None
        except Exception:
            bybit_oi = None

        # Gate.io: open interest in contracts (total_size / 10000)
        try:
            resp = requests.get(GATEIO_URL, timeout=5)
            resp.raise_for_status()
            tickers = resp.json()
            gate_oi = None
            for t in tickers:
                if t.get("contract") == "BTC_USDT":
                    gate_oi = float(t.get("total_size", 0.0)) / 10000
                    break
        except Exception:
            gate_oi = None

        # Bitget: number of contracts
        try:
            resp = requests.get(
                BITGET_URL,
                params={"symbol": "BTCUSDT", "productType": "USDT-FUTURES"},
                timeout=5
            )
            resp.raise_for_status()
            js = resp.json()
            if js.get("code") == "00000":
                lst = js["data"].get("openInterestList", [])
                bitget_oi = float(lst[0].get("size", 0.0)) if lst else None
            else:
                bitget_oi = None
        except Exception:
            bitget_oi = None


        # Hyperliquid: open interest from info endpoint
        try:
            resp = requests.post(
                HYPER_URL,
                json={"type": "metaAndAssetCtxs"},
                timeout=5
            )
            resp.raise_for_status()
            js = resp.json()
            ctxs = js[1] if isinstance(js, list) and len(js) > 1 else []
            hyper_oi = float(ctxs[0].get("openInterest", 0.0)) if ctxs else None
        except Exception:
            hyper_oi = None

        # HTX: position quantity in BTC (amount field)
        try:
            resp = requests.get(
                "https://api.hbdm.com/linear-swap-api/v1/swap_open_interest",
                params={"contract_code": "BTC-USDT"},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])
            htx_oi = float(data[0].get("amount", 0.0)) if isinstance(data, list) and data else None
        except Exception:
            htx_oi = None

        # BitMEX: convert USD-denominated OI into BTC exposure
        try:
            resp = requests.get(
                "https://www.bitmex.com/api/v1/instrument",
                params={"symbol": "XBTUSD"},
                timeout=5
            );
            resp.raise_for_status()
            inst = resp.json()
            if isinstance(inst, list) and inst:
                oi_usd = float(inst[0].get("openInterest", 0.0))
                last_price = float(inst[0].get("lastPrice", 0.0))
                bitmex_oi = oi_usd / last_price if last_price else None
            else:
                bitmex_oi = None
        except Exception:
            bitmex_oi = None

        # Print results

        print(f"{ts}, {binance_oi}, {okx_oi}, {bybit_oi}, {gate_oi}, {bitget_oi}, {hyper_oi}, {htx_oi}, {bitmex_oi}")


        await asyncio.sleep(60)

def main():
    print("Starting OI loop (UTC; Binance, OKX, Bybit, Gate.io, Bitget, Hyperliquid, HTX, BitMEX)")
    try:
        asyncio.run(run_oi_loop())
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    main()
