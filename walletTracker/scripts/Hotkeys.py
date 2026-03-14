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


def waitForOrderFill(orderId):
    """ Wait until the post-only order is filled before placing TP & SL """
    print(f"🔄 Waiting for order {orderId} to be filled...")
    while True:
        orders = tradeAPI.get_order(instId=INST_ID, ordId=orderId)
        if orders["code"] == "0" and orders["data"]:
            status = orders["data"][0]["state"]
            if status == "filled":
                print(f"✅ Order {orderId} has been filled.")
                return True
            elif status in ["canceled", "rejected"]:
                print(f"❌ Order {orderId} was {status}. Retrying...")
                return False
        time.sleep(1)  # Wait before checking again


def placeTpSl(orderSide, entryPrice, orderSize):
    """ Automatically place Take Profit & Stop Loss orders as Post-Only Limit Orders """
    if orderSide == "buy":  # Long Position
        tpPrice = (entryPrice * (1 + TP_PERCENT / 100))   # TP at +1.5% + 0.1
        slPrice = (entryPrice * (1 - SL_PERCENT / 100))  # SL at -0.5% - 0.1
        tpSide, slSide = "sell", "sell"
    elif orderSide == "sell":  # Short Position
        tpPrice = (entryPrice * (1 - TP_PERCENT / 100))
        slPrice = (entryPrice * (1 + SL_PERCENT / 100))
        tpSide, slSide = "buy", "buy"
    else:
        print("❌ Invalid order side for TP/SL.")
        return

    print(f"🚀 Placing TP at {tpPrice:.2f} and SL at {slPrice:.2f} for {orderSize} contracts.")

    # ✅ Post-Only Take Profit Order
    tpOrder = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=tpSide,
        posSide="long" if orderSide == "buy" else "short",
        ordType="post_only",  # Ensures Maker Fees
        px=str(tpPrice),  # TP Limit Price
        sz=orderSize,
        reduceOnly="true"
    )
    if tpOrder["code"] == "0":
        print(f"✅ TP Order Placed at {tpPrice:.2f} USDT (Post-Only)")
    else:
        print(f"❌ Error placing TP: {tpOrder}")

    # ✅ Post-Only Stop Loss Order
    slOrder = tradeAPI.place_order(
        instId=INST_ID,
        tdMode="isolated",
        side=slSide,
        posSide="long" if orderSide == "buy" else "short",
        ordType="post_only",  # Ensures Maker Fees
        px=str(slPrice),  # SL Limit Price
        sz=orderSize,
        reduceOnly="true"
    )
    if slOrder["code"] == "0":
        print(f"✅ SL Order Placed at {slPrice:.2f} USDT (Post-Only)")
    else:
        print(f"❌ Error placing SL: {slOrder}")


# 🔹 Start Trading Loop
while True:
    markPriceData = publicAPI.get_mark_price(instType="SWAP", instId=INST_ID)

    if markPriceData["code"] == "0":
        markPrice = float(markPriceData["data"][0]["markPx"])
        print(f"✅ Mark Price: {markPrice} USDT")
    else:
        print(f"❌ Failed to fetch mark price: {markPriceData}")
        continue

    action = input("Enter 'a' to Buy (Long), 'd' to Sell (Short), 'q' to Quit: ").strip().lower()

    if action == "a":
        buyPrice = markPrice * 0.999999999  # ✅ Adjusted to prevent instant execution
        print(f"✅ Executing Buy Post-Only Order at {buyPrice:.2f}...")
        orderResult = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side="buy",
            posSide="long",
            ordType="post_only",
            px=str(buyPrice),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )
        if orderResult["code"] == "0":
            orderId = orderResult["data"][0]["ordId"]
            print(f"✅ Buy Order Placed. Order ID: {orderId}")
            if waitForOrderFill(orderId):
                placeTpSl("buy", buyPrice, ORDER_SIZE)
        else:
            print(f"❌ Error placing buy order: {orderResult}")

    elif action == "d":
        sellPrice = markPrice * 1.0000000001  # ✅ Adjusted to prevent instant execution
        print(f"✅ Executing Sell Post-Only Order at {sellPrice:.2f}...")
        orderResult = tradeAPI.place_order(
            instId=INST_ID,
            tdMode="isolated",
            side="sell",
            posSide="short",
            ordType="post_only",
            px=str(sellPrice),
            sz=ORDER_SIZE,
            reduceOnly="false"
        )
        if orderResult["code"] == "0":
            orderId = orderResult["data"][0]["ordId"]
            print(f"✅ Sell Order Placed. Order ID: {orderId}")
            if waitForOrderFill(orderId):
                placeTpSl("sell", sellPrice, ORDER_SIZE)
        else:
            print(f"❌ Error placing sell order: {orderResult}")

    elif action == "q":
        print("🚪 Exiting Trading Script...")
        break

    else:
        print("❌ Invalid input!")

    time.sleep(1)