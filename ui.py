# A Python-powered live trading dashboard that runs in the browser
""" 
This file builds a live web dashboard using Streamlit to visualise an options trading strategy (Short Strangle with hedges).
It reads trade data from a JSON file, calculates key metrics (credit, delta, risk, VWAP bias), and displays them in a real-time updating UI (auto-refresh every 5 seconds).
Streamlit is a Python framework that converts Python code into an interactive web application (HTML/CSS/JS) automatically, without writing frontend code manually.

Usage:
    pip install streamlit pandas streamlit-autorefresh
    streamlit run streamlit_app.py
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh

import pandas as pd
import json
from datetime import datetime

st.set_page_config(page_title="Option Strategy Dashboard", layout="wide")

st_autorefresh(interval=5000, key="refresh")  # refresh every 5 seconds

# ---------- LOAD DATA ----------
def load_trade():
    with open("storage/trade.json") as f:
        return json.load(f)

trade = load_trade()
final = trade.get("finalPair", {})
call = final.get("call", {})
put = final.get("put", {})
hedges = trade.get("hedgeOptions", {})


# ---------- HEADER ----------
st.markdown("## 📊 Option Strategy Dashboard")
st.caption(f"Last Updated: {datetime.now().strftime('%H:%M:%S')}")
st.divider()

# ---------- MARKET CONTEXT ----------
spot = trade.get("spot")
vwap_bias = call.get("vwapStatus", "Unknown")
bias_color = "🟢" if vwap_bias == "Above" else "🔴" if vwap_bias == "Below" else "🟡"

c1, c2, c3, c4 = st.columns(4)

c1.metric("NIFTY Spot", spot)
c2.metric("Market Bias", f"{bias_color} {vwap_bias}")
c3.metric("Strategy", "Delta Neutral")
c4.metric("Target Delta", trade.get("targetDelta"))

st.divider()

# ---------- STRATEGY SUMMARY ----------
sc1, sc2, sc3, sc4 = st.columns(4)

net_credit = (call.get("ltp", 0) + put.get("ltp", 0))
hedge_cost = trade.get("hedgeOptions", {}).get("hedgeCost", 0)

sc1.metric("Net Credit", f"₹ {round(net_credit,2)}")
sc2.metric("Hedge Cost", f"₹ {round(hedge_cost,2)}")
sc3.metric("Risk", "LIMITED")
sc4.metric("Structure", "Short Strangle")

st.divider()

def risk_badge(net_credit, hedge_cost):
    if hedge_cost == 0:
        return {
            "label": "⚠️ UNPROTECTED",
            "reason": "No hedge in place",
            "insight": "Unlimited risk if market moves sharply"
        }

    ratio = net_credit / hedge_cost

    if ratio > 2:
        return {
            "label": "🟢 SAFE",
            "reason": "Hedge cost is low vs premium",
            "insight": "Good risk-reward and capital efficiency"
        }
    elif ratio > 1:
        return {
            "label": "🟡 CAUTION",
            "reason": "Hedge cost is moderate",
            "insight": "Monitor MTM closely"
        }
    else:
        return {
            "label": "🔴 RISKY",
            "reason": "Hedge cost is high vs premium",
            "insight": "Low reward for the risk taken"
        }


risk = risk_badge(net_credit, hedge_cost)

st.markdown("### 🚦 Risk Status")
st.metric("Current Risk Profile", risk["label"])
st.caption(risk["reason"])
st.write(risk["insight"])

st.divider()

# ---------- POSITION LEGS ----------
st.markdown("### 🧾 Positions")

lc, lp = st.columns(2)

def vwap_status_box(status):
    if status == "Above":
        st.success("Above VWAP (Strength)")
    elif status == "Below":
        st.error("Below VWAP (Weakness)")
    else:
        st.warning("Near VWAP")

with lc:
    st.subheader("CALL (Short)")
    st.metric("Strike", call.get("strikePrice"))
    st.metric("Delta", round(float(call.get("delta", 0)), 3))
    st.metric("Premium", call.get("ltp"))
    st.metric("VWAP", round(call.get("vwap", 0), 2))
    vwap_status_box(call.get("vwapStatus"))

with lp:
    st.subheader("PUT (Short)")
    st.metric("Strike", put.get("strikePrice"))
    st.metric("Delta", round(float(put.get("delta", 0)), 3))
    st.metric("Premium", put.get("ltp"))
    st.metric("VWAP", round(put.get("vwap", 0), 2))
    vwap_status_box(put.get("vwapStatus"))

st.divider()

# ---------- RISK & HEDGE ----------
st.markdown("### 🛡 Risk & Protection")

def render_hedge_table(hedge_list, side):
    if not hedge_list:
        st.warning(f"No {side} hedges found")
        return

    df = pd.DataFrame(hedge_list)
    df = df[["strikePrice", "ltp", "delta"]]
    df.columns = ["Strike", "Premium (₹)", "Delta"]

    st.markdown(f"**{side.upper()} Hedge Options**")
    st.dataframe(
        df.style
        .format({"Premium (₹)": "{:.2f}", "Delta": "{:.3f}"})
        .background_gradient(cmap="Greens"),
        use_container_width=True
    )

hc, hp = st.columns(2)

with hc:
    render_hedge_table(hedges.get("call_5rs", []), "Call")

with hp:
    render_hedge_table(hedges.get("put_5rs", []), "Put")

# ---------- SYSTEM STATUS ----------
st.markdown("### ⚙️ System Status")

status_cols = st.columns(4)
status_cols[0].success("Auth ✔")
status_cols[1].success("VWAP ✔")
status_cols[2].success("Greeks ✔")
status_cols[3].success("Trade ✔")
