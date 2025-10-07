import okx.PublicData as PublicData
import okx.Trade as Trade
import okx.Account as Account
import time

# ✅ OKX API Credentials
API_KEY = "ab45a745-df91-4bc3-a223-0a6370e3baaf"
SECRET_KEY = "7A40CED95DC92E240DFE3FA0CD8CD649"
PASSPHRASE = "Crimsic73!"

FLAG = "0"  # 0 = Live Trading, 1 = Demo Trading

# ✅ Initialize APIs
publicAPI = PublicData.PublicAPI(API_KEY, SECRET_KEY, PASSPHRASE, False, FLAG)
tradeAPI = Trade.TradeAPI(API_KEY, SECRET_KEY, PASSPHRASE, False, FLAG)
accountAPI = Account.AccountAPI(API_KEY, SECRET_KEY, PASSPHRASE, False, FLAG)

# ✅ Trading Pair & Order Settings
INST_ID = "BTC-USDT-SWAP"  # Trading instrument (Perpetual Swap)
ORDER_SIZE = "0.5"  # Number of contracts to trade
LEVERAGE = "30"  # 30x Leverage

# ✅ Take Profit & Stop Loss Settings (Percentage)
TP_PERCENT = 0.1  # 1.5% above entry for TP
SL_PERCENT = 0.05  # 0.5% below entry for SL

# ✅ Ensure Long-Short Mode is Enabled
accountAPI.set_position_mode(posMode="long_short_mode")

# ✅ Set 30x Leverage in Isolated Margin Mode
accountAPI.set_leverage(instId=INST_ID, lever=LEVERAGE, mgnMode="isolated")


def wait_for_order_fill(order_id):
    """ Wait until the post-only order is filled before placing TP & SL """
    print(f"🔄 Waiting for order {order_id} to be filled...")
    while True:
        orders = tradeAPI.get_order(instId=INST_ID, ordId=order_id)
        if orders["code"] == "0" and orders["data"]:
            status = orders["data"][0]["state"]
            if status == "filled":
                print(f"✅ Order {order_id} has been filled.")
                return True
            elif status in ["canceled", "rejected"]:
                print(f"❌ Order {order_id} was {status}. Retrying...")
                return False
        time.sleep(1)  # Wait before checking again


def place_tp_sl(order_side, entry_price, order_size):
    """ Automatically place Take Profit & Stop Loss orders as Post-Only Limit Orders """
    if order_side == "buy":  # Long Position
        tp_price = (entry_price * (1 + TP_PERCENT / 100))   # TP at +1.5% + 0.1
        sl_price = (entry_price * (1 - SL_PERCENT / 100))  # SL at -0.5% - 0.1
        tp_side, sl_side = "sell", "sell"
    elif order_side == "sell":  # Short Position
        tp_price = (entry_price * (1 - TP_PERCENT / 100))
        sl_price = (entry_price * (1 + SL_PERCENT / 100))
        tp_side, sl_side = "buy", "buy"
    else:
        print("❌ Invalid order side for TP/SL.")
        return

    print(f"🚀 Placing TP at {tp_price:.2f} and SL at {sl_price:.2f} for {order_size} contracts.")

    # ✅ Post-Only Take Profit Order
    tp_order = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=tp_side,
        posSide="long" if order_side == "buy" else "short",
        ordType="post_only",  # Ensures Maker Fees
        px=str(tp_price),  # TP Limit Price
        sz=order_size,
        reduceOnly="true"
    )
    if tp_order["code"] == "0":
        print(f"✅ TP Order Placed at {tp_price:.2f} USDT (Post-Only)")
    else:
        print(f"❌ Error placing TP: {tp_order}")

    # ✅ Post-Only Stop Loss Order
    sl_order = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=sl_side,
        posSide="long" if order_side == "buy" else "short",
        ordType="post_only",  # Ensures Maker Fees
        px=str(sl_price),  # SL Limit Price
        sz=order_size,
        reduceOnly="true"
    )
    if sl_order["code"] == "0":
        print(f"✅ SL Order Placed at {sl_price:.2f} USDT (Post-Only)")
    else:
        print(f"❌ Error placing SL: {sl_order}")


# 🔹 Start Trading Loop
while True:
    mark_price_data = publicAPI.get_mark_price(instType="SWAP", instId=INST_ID)

    if mark_price_data["code"] == "0":
        mark_price = float(mark_price_data["data"][0]["markPx"])
        print(f"✅ Mark Price: {mark_price} USDT")
    else:
        print(f"❌ Failed to fetch mark price: {mark_price_data}")
        continue

    action = input("Enter 'a' to Buy (Long), 'd' to Sell (Short), 'q' to Quit: ").strip().lower()

    if action == "a":
        buy_price = mark_price * 0.999999999  # ✅ Adjusted to prevent instant execution
        print(f"✅ Executing Buy Post-Only Order at {buy_price:.2f}...")
        order_result = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side="buy",
            posSide="long",
            ordType="post_only",
            px=str(buy_price),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )
        if order_result["code"] == "0":
            order_id = order_result["data"][0]["ordId"]
            print(f"✅ Buy Order Placed. Order ID: {order_id}")
            if wait_for_order_fill(order_id):
                place_tp_sl("buy", buy_price, ORDER_SIZE)
        else:
            print(f"❌ Error placing buy order: {order_result}")

    elif action == "d":
        sell_price = mark_price * 1.0000000001  # ✅ Adjusted to prevent instant execution
        print(f"✅ Executing Sell Post-Only Order at {sell_price:.2f}...")
        order_result = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side="sell",
            posSide="short",
            ordType="post_only",
            px=str(sell_price),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )
        if order_result["code"] == "0":
            order_id = order_result["data"][0]["ordId"]
            print(f"✅ Sell Order Placed. Order ID: {order_id}")
            if wait_for_order_fill(order_id):
                place_tp_sl("sell", sell_price, ORDER_SIZE)
        else:
            print(f"❌ Error placing sell order: {order_result}")

    elif action == "q":
        print("🚪 Exiting Trading Script...")
        break

    else:
        print("❌ Invalid input!")

    time.sleep(1)