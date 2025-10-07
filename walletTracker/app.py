import websocket
import json
import threading
from flask import Flask, render_template, jsonify

app = Flask(__name__)
order_book_data = {"asks": [], "bids": []}


def merge_order_book(new_data, side):
    global order_book_data
    updated_orders = {order[0]: str(float(order[0]) * float(order[1])) for order in new_data}  # Convert BTC to USDT
    existing_orders = {order[0]: order[1] for order in order_book_data[side]}  # Existing orders dict

    # Update existing orders and add new ones
    existing_orders.update(updated_orders)

    # Remove orders where amount = 0 (these should be deleted from the book)
    order_book_data[side] = [[price, amount] for price, amount in existing_orders.items() if float(amount) > 0]

    # Sort order book correctly
    order_book_data["asks"].sort(key=lambda x: float(x[0]))  # Lowest ask price first
    order_book_data["bids"].sort(key=lambda x: float(x[0]), reverse=True)  # Highest bid price first


def on_message(ws, message):
    global order_book_data
    data = json.loads(message)

    if "data" in data:
        new_data = data["data"][0]  # Get the first order book update
        if "asks" in new_data:
            merge_order_book(new_data["asks"], "asks")  # Merge ask orders
        if "bids" in new_data:
            merge_order_book(new_data["bids"], "bids")  # Merge bid orders


def on_error(ws, error):
    print(f"Error: {error}")


def on_close(ws, close_status_code, close_msg):
    print("WebSocket closed")


def on_open(ws):
    subscribe_message = {
        "op": "subscribe",
        "args": [
            {
                "channel": "books-l2-tbt",
                "instId": "BTC-USDT-SWAP"
            }
        ]
    }
    ws.send(json.dumps(subscribe_message))


def run_ws():
    ws_url = "wss://ws.okx.com:8443/ws/v5/public"
    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.on_open = on_open
    ws.run_forever()


def start_websocket_thread():
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/orderbook")
def orderbook():
    return jsonify(order_book_data)


if __name__ == "__main__":
    start_websocket_thread()
    app.run(debug=True, host="0.0.0.0", port=5000)
