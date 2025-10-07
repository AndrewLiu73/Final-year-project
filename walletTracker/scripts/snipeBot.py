import okx.PublicData as PublicData
import okx.Trade as Trade
import okx.Account as Account
import datetime
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

# ✅ Trading Settings
INST_ID = "BTC-USDT-SWAP"  # Perpetual Swap Trading Pair
ORDER_SIZE = "1"  # Number of contracts
LEVERAGE = "30"  # 30x Leverage
ORDER_UPDATE_INTERVAL = 1200  # 20 minutes (1200 sec)
ORDER_DISTANCE_PERCENT = 2  # Place orders 2% away from price
TP_PERCENT = 1.5  # Take Profit at +1.5%
SL_PERCENT = 0.5  # Stop Loss at -0.5%

# ✅ Ensure Long-Short Mode is Enabled
accountAPI.set_position_mode(posMode="long_short_mode")
accountAPI.set_leverage(instId=INST_ID, lever=LEVERAGE, mgnMode="isolated")

# ✅ Store order details
last_long_order_id = None
last_short_order_id = None
first_run = True  # ✅ Flag to track first cycle


def get_active_orders():
    """ Get currently active (unfilled) post-only orders. """
    orders = tradeAPI.get_order_list(instId=INST_ID)
    active_orders = {"long": None, "short": None}

    if orders["code"] == "0" and orders["data"]:
        for order in orders["data"]:
            if order["posSide"] == "long":
                active_orders["long"] = order["ordId"]
            elif order["posSide"] == "short":
                active_orders["short"] = order["ordId"]
    return active_orders


def get_open_positions():
    """ Get current open positions. """
    positions = accountAPI.get_positions(instId=INST_ID)

    long_entry_price = None
    short_entry_price = None
    long_size = 0
    short_size = 0

    if positions["code"] == "0" and positions["data"]:
        for pos in positions["data"]:
            avg_price = pos.get("avgPx", "0")  # ✅ Default to "0" if missing
            pos_size = pos.get("pos", "0")  # ✅ Default to "0" if missing

            if avg_price.strip() == "":  # ✅ Check if it's an empty string
                avg_price = "0"

            if pos_size.strip() == "":  # ✅ Check if it's an empty string
                pos_size = "0"

            if pos["posSide"] == "long":
                long_entry_price = float(avg_price)
                long_size = float(pos_size)
            elif pos["posSide"] == "short":
                short_entry_price = float(avg_price)
                short_size = float(pos_size)

    return long_entry_price, long_size, short_entry_price, short_size


def place_tp_sl_orders(pos_side, entry_price, size):
    """ Places Take Profit (TP) and Stop Loss (SL) orders after a position is filled. """
    if pos_side == "long":
        tp_price = entry_price * (1 + TP_PERCENT / 100)  # ✅ TP at +1.5%
        sl_price = entry_price * (1 - SL_PERCENT / 100)  # ✅ SL at -0.5%
        close_side = "sell"
    else:
        tp_price = entry_price * (1 - TP_PERCENT / 100)  # ✅ TP at -1.5%
        sl_price = entry_price * (1 + SL_PERCENT / 100)  # ✅ SL at +0.5%
        close_side = "buy"

    print(f"🎯 Placing TP & SL for {pos_side.upper()} Position: Entry={entry_price:.2f}, TP={tp_price:.2f}, SL={sl_price:.2f}")

    # ✅ Place Take Profit (TP) Limit Order
    tp_order = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=close_side,
        posSide=pos_side,
        ordType="limit",
        px=str(round(tp_price, 2)),  # ✅ Limit order for TP
        sz=str(size),
        reduceOnly="true"
    )
    if tp_order["code"] == "0":
        print(f"✅ TP Order Placed at {tp_price:.2f}")
    else:
        print(f"❌ Error placing TP: {tp_order}")

    # ✅ Place Stop Loss (SL) as a **Trigger Order**
    sl_order = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=close_side,
        posSide=pos_side,
        ordType="trigger",  # ✅ Correct SL order type
        slTriggerPx=str(round(sl_price, 2)),  # ✅ SL Trigger Price
        sz=str(size),
        reduceOnly="true"
    )
    if sl_order["code"] == "0":
        print(f"✅ SL Order Placed at {sl_price:.2f}")
    else:
        print(f"❌ Error placing SL: {sl_order}")



def amend_or_place_order(order_id, side, pos_side, new_price):
    """ Places or amends an order. """
    global first_run

    if first_run or order_id is None:
        print(f"🚀 Placing {pos_side} order at {new_price:.2f}")
        new_order = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side=side,
            posSide=pos_side,
            ordType="post_only",
            px=str(round(new_price, 2)),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )

        if new_order["code"] == "0":
            new_order_id = new_order["data"][0]["ordId"]
            print(f"✅ New {pos_side.capitalize()} Order Placed at {new_price:.2f} (Post-Only)")
            return new_order_id
        else:
            print(f"❌ Error placing {pos_side} order: {new_order}")
            return None

    print(f"🔄 Amending {pos_side} Order ID: {order_id} to new price {new_price:.2f}")
    amend_response = tradeAPI.amend_order(instId=INST_ID, ordId=order_id, newPx=str(round(new_price, 2)))

    if amend_response["code"] == "0":
        print(f"✅ {pos_side.capitalize()} Order Amended to {new_price:.2f}")
        return order_id
    else:
        print(f"❌ Failed to amend {pos_side} order. Retrying...")
        return None


# 🔹 **Start the bot, updating every 20 minutes**
while True:
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔄 Updating Orders | Current Time: {current_time}")

    # ✅ Fetch latest mark price
    mark_price = float(publicAPI.get_mark_price(instType="SWAP", instId=INST_ID)["data"][0]["markPx"])
    long_price = mark_price * (1 - ORDER_DISTANCE_PERCENT / 100)  # 2% lower
    short_price = mark_price * (1 + ORDER_DISTANCE_PERCENT / 100)  # 2% higher

    # ✅ Get active orders
    active_orders = get_active_orders()

    # ✅ First cycle places orders, subsequent cycles amend them
    last_long_order_id = amend_or_place_order(active_orders["long"], "buy", "long", long_price)
    last_short_order_id = amend_or_place_order(active_orders["short"], "sell", "short", short_price)

    # ✅ Check for filled positions and set TP/SL
    long_entry, long_size, short_entry, short_size = get_open_positions()

    if long_size > 0:
        place_tp_sl_orders("long", long_entry, long_size)

    if short_size > 0:
        place_tp_sl_orders("short", short_entry, short_size)

    # ✅ Ensure First Cycle Completes Properly
    first_run = False

    # ✅ Show next update time
    next_update = datetime.datetime.now() + datetime.timedelta(seconds=ORDER_UPDATE_INTERVAL)
    print(f"⏳ Waiting {ORDER_UPDATE_INTERVAL // 60} minutes | Next Update: {next_update.strftime('%Y-%m-%d %H:%M:%S')}\n")

    time.sleep(ORDER_UPDATE_INTERVAL)
