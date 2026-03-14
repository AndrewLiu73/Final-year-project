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
lastLongOrderId = None
lastShortOrderId = None
firstRun = True  # ✅ Flag to track first cycle


def getActiveOrders():
    """ Get currently active (unfilled) post-only orders. """
    orders = tradeAPI.get_order_list(instId=INST_ID)
    activeOrders = {"long": None, "short": None}

    if orders["code"] == "0" and orders["data"]:
        for order in orders["data"]:
            if order["posSide"] == "long":
                activeOrders["long"] = order["ordId"]
            elif order["posSide"] == "short":
                activeOrders["short"] = order["ordId"]
    return activeOrders


def getOpenPositions():
    """ Get current open positions. """
    positions = accountAPI.get_positions(instId=INST_ID)

    longEntryPrice = None
    shortEntryPrice = None
    longSize = 0
    shortSize = 0

    if positions["code"] == "0" and positions["data"]:
        for pos in positions["data"]:
            avgPrice = pos.get("avgPx", "0")  # ✅ Default to "0" if missing
            posSize = pos.get("pos", "0")  # ✅ Default to "0" if missing

            if avgPrice.strip() == "":  # ✅ Check if it's an empty string
                avgPrice = "0"

            if posSize.strip() == "":  # ✅ Check if it's an empty string
                posSize = "0"

            if pos["posSide"] == "long":
                longEntryPrice = float(avgPrice)
                longSize = float(posSize)
            elif pos["posSide"] == "short":
                shortEntryPrice = float(avgPrice)
                shortSize = float(posSize)

    return longEntryPrice, longSize, shortEntryPrice, shortSize


def placeTpSlOrders(posSide, entryPrice, size):
    """ Places Take Profit (TP) and Stop Loss (SL) orders after a position is filled. """
    if posSide == "long":
        tpPrice = entryPrice * (1 + TP_PERCENT / 100)  # ✅ TP at +1.5%
        slPrice = entryPrice * (1 - SL_PERCENT / 100)  # ✅ SL at -0.5%
        closeSide = "sell"
    else:
        tpPrice = entryPrice * (1 - TP_PERCENT / 100)  # ✅ TP at -1.5%
        slPrice = entryPrice * (1 + SL_PERCENT / 100)  # ✅ SL at +0.5%
        closeSide = "buy"

    print(f"🎯 Placing TP & SL for {posSide.upper()} Position: Entry={entryPrice:.2f}, TP={tpPrice:.2f}, SL={slPrice:.2f}")

    # ✅ Place Take Profit (TP) Limit Order
    tpOrder = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=closeSide,
        posSide=posSide,
        ordType="limit",
        px=str(round(tpPrice, 2)),  # ✅ Limit order for TP
        sz=str(size),
        reduceOnly="true"
    )
    if tpOrder["code"] == "0":
        print(f"✅ TP Order Placed at {tpPrice:.2f}")
    else:
        print(f"❌ Error placing TP: {tpOrder}")

    # ✅ Place Stop Loss (SL) as a **Trigger Order**
    slOrder = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=closeSide,
        posSide=posSide,
        ordType="trigger",  # ✅ Correct SL order type
        slTriggerPx=str(round(slPrice, 2)),  # ✅ SL Trigger Price
        sz=str(size),
        reduceOnly="true"
    )
    if slOrder["code"] == "0":
        print(f"✅ SL Order Placed at {slPrice:.2f}")
    else:
        print(f"❌ Error placing SL: {slOrder}")



def amendOrPlaceOrder(orderId, side, posSide, newPrice):
    """ Places or amends an order. """
    global firstRun

    if firstRun or orderId is None:
        print(f"🚀 Placing {posSide} order at {newPrice:.2f}")
        newOrder = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side=side,
            posSide=posSide,
            ordType="post_only",
            px=str(round(newPrice, 2)),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )

        if newOrder["code"] == "0":
            newOrderId = newOrder["data"][0]["ordId"]
            print(f"✅ New {posSide.capitalize()} Order Placed at {newPrice:.2f} (Post-Only)")
            return newOrderId
        else:
            print(f"❌ Error placing {posSide} order: {newOrder}")
            return None

    print(f"🔄 Amending {posSide} Order ID: {orderId} to new price {newPrice:.2f}")
    amendResponse = tradeAPI.amend_order(instId=INST_ID, ordId=orderId, newPx=str(round(newPrice, 2)))

    if amendResponse["code"] == "0":
        print(f"✅ {posSide.capitalize()} Order Amended to {newPrice:.2f}")
        return orderId
    else:
        print(f"❌ Failed to amend {posSide} order. Retrying...")
        return None


# 🔹 **Start the bot, updating every 20 minutes**
while True:
    currentTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🔄 Updating Orders | Current Time: {currentTime}")

    # ✅ Fetch latest mark price
    markPrice = float(publicAPI.get_mark_price(instType="SWAP", instId=INST_ID)["data"][0]["markPx"])
    longPrice = markPrice * (1 - ORDER_DISTANCE_PERCENT / 100)  # 2% lower
    shortPrice = markPrice * (1 + ORDER_DISTANCE_PERCENT / 100)  # 2% higher

    # ✅ Get active orders
    activeOrders = getActiveOrders()

    # ✅ First cycle places orders, subsequent cycles amend them
    lastLongOrderId = amendOrPlaceOrder(activeOrders["long"], "buy", "long", longPrice)
    lastShortOrderId = amendOrPlaceOrder(activeOrders["short"], "sell", "short", shortPrice)

    # ✅ Check for filled positions and set TP/SL
    longEntry, longSize, shortEntry, shortSize = getOpenPositions()

    if longSize > 0:
        placeTpSlOrders("long", longEntry, longSize)

    if shortSize > 0:
        placeTpSlOrders("short", shortEntry, shortSize)

    # ✅ Ensure First Cycle Completes Properly
    firstRun = False

    # ✅ Show next update time
    nextUpdate = datetime.datetime.now() + datetime.timedelta(seconds=ORDER_UPDATE_INTERVAL)
    print(f"⏳ Waiting {ORDER_UPDATE_INTERVAL // 60} minutes | Next Update: {nextUpdate.strftime('%Y-%m-%d %H:%M:%S')}\n")

    time.sleep(ORDER_UPDATE_INTERVAL)
