import streamlit as st
import json

st.set_page_config(layout="wide")  # optional for widescreen layouts

st.title("Millionaire Wallet Bias Dashboard")

# Load bias summary from file
with open("bias_summary.json") as f:
    data = json.load(f)

aggregate = data["aggregate_bias"]
wallets = data["wallet_bias"]

st.header("Aggregate Coin Bias")
for coin, stats in aggregate.items():
    st.subheader(coin)
    col1, col2 = st.columns([4, 1])
    with col1:
        st.write(f"Bias: **{stats['direction']}**")
        st.progress(stats["long_pct"] / 100)
    with col2:
        st.metric("Long %", f"{stats['long_pct']:.2f}%")
        st.metric("Short %", f"{stats['short_pct']:.2f}%")
    st.write(
        f"Long: ${stats['long']:.2f} ({stats['long_pct']:.2f}%) &nbsp;|&nbsp; "
        f"Short: ${stats['short']:.2f} ({stats['short_pct']:.2f}%)"
    )
    st.markdown("---")

st.header("Individual Wallet Bias")
wallet_list = list(wallets.keys())
selected_wallets = st.multiselect("Select wallets to view", wallet_list, default=wallet_list[:10])
for wallet in selected_wallets:
    st.markdown(f"**Wallet:** `{wallet}`")
    coins = wallets[wallet]
    for coin, stats in coins.items():
        st.markdown(
            f"- {coin}: {stats['direction']} | "
            f"Long ${stats['long']:.2f} ({stats['long_pct']:.1f}%) | "
            f"Short ${stats['short']:.2f} ({stats['short_pct']:.1f}%)"
        )
    st.markdown("---")
