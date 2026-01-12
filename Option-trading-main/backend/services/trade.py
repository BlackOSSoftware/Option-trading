import json
import requests
from datetime import datetime
from typing import TypedDict, Dict


class Instrument(TypedDict):
    name: str
    expiry: str
    strikePrice: str
    optionType: str
    symbolToken: str


class FinalPair(TypedDict):
    call: Instrument
    put: Instrument
    callPremium: float
    putPremium: float
    premiumDiff: float
    distance: float


# ---------------------------
# Load user.json  (Correct Path)
# ---------------------------
def load_user_config() -> dict:
    with open("storage/user.json", "r") as f:
        return json.load(f)


# ---------------------------
# Load trade.json (Correct Path)
# ---------------------------
def load_trade_json() -> dict:
    with open("storage/trade.json", "r") as f:
        return json.load(f)


# ---------------------------
# Save trade.json (Correct Path)
# ---------------------------
def save_trade_json(data: dict) -> None:
    with open("storage/trade.json", "w") as f:
        json.dump(data, f, indent=4)


# -----------------------------------------
# SAFE Angel Broking LTP Fetch Function
# -----------------------------------------
def get_ltp_from_angel(user: dict, exchange: str, tradingsymbol: str, token: str) -> float:
    url = "https://apiconnect.angelone.in/rest/secure/angelbroking/order/v1/getLtpData"

    headers = {
        "Authorization": f"Bearer {user['jwtToken']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-PrivateKey": user["private_key"],
        "X-ClientLocalIP": user["local_ip"],
        "X-ClientPublicIP": user["public_ip"],
        "X-MACAddress": user["mac_address"],
        "X-UserType": user["user_type"],
        "X-SourceID": user["source_id"],
    }

    payload = {
        "exchange": exchange,
        "tradingsymbol": tradingsymbol,
        "symboltoken": token,
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data.get("status"):
            print("LTP error:", data)
            return 0.0
        # Angel usually returns LTP inside data["ltp"] or data["data"]["ltp"]
        d = data.get("data") or {}
        ltp = float(d.get("ltp", 0.0))
        print(f"LTP {tradingsymbol} ({token}) = {ltp}")
        return ltp
    except Exception as e:
        print("LTP exception:", e)
        return 0.0


# -----------------------------------------
# MAIN CALCULATION
# -----------------------------------------
def update_premium_levels() -> None:
    user = load_user_config()
    trade_data = load_trade_json()

    final_pair: FinalPair = trade_data["finalPair"]

    # Tokens from trade.json
    call_token = final_pair["call"]["symbolToken"]
    put_token = final_pair["put"]["symbolToken"]
    call_ts = final_pair["call"]["tradingsymbol"]
    put_ts = final_pair["put"]["tradingsymbol"]


    # Fetch Premiums
    call_price = get_ltp_from_angel(user, "NFO", call_ts, call_token)
    put_price = get_ltp_from_angel(user, "NFO", put_ts, put_token)

    # 40% CALCULATION 
    total = call_price + put_price
    forty_percent = round(total * 0.40, 2)

    # SOLD PRICES (entry time LTP)
    sold_call_price = final_pair["call"].get("ltp", 0.0) or call_price
    sold_put_price = final_pair["put"].get("ltp", 0.0) or put_price
    total_sold_premium = sold_call_price + sold_put_price
    threshold_40_sold = total_sold_premium * 0.40

    # LIVE LOSS (40% sold - live total)
    live_loss = threshold_40_sold - total

    # STRATEGY SIGNALS 
    hedge_needed = live_loss > 0
    add_new_option = live_loss > (threshold_40_sold * 0.5)
    total_strategy_loss = abs(live_loss) * 2  # 2 lots
    exit_strategy = total_strategy_loss >= 1500

    # Update values
    final_pair["callPremium"] = call_price
    final_pair["putPremium"] = put_price
    final_pair["premiumDiff"] = abs(call_price - put_price)
    final_pair["distance"] = forty_percent

    # Save COMPLETE strategy status
    trade_data["strategyStatus"] = {
        'timestamp': datetime.now().isoformat(),
        'sold_call': round(sold_call_price, 2),
        'sold_put': round(sold_put_price, 2),
        'live_call': round(call_price, 2),
        'live_put': round(put_price, 2),
        'total_sold': round(total_sold_premium, 2),
        'threshold_40_sold': round(threshold_40_sold, 2),
        'live_total': round(total, 2),
        'live_loss': round(live_loss, 2),
        'hedge_needed': hedge_needed,
        'add_new_option': add_new_option,
        'exit_strategy': exit_strategy,
        'total_strategy_loss': round(total_strategy_loss, 2)
    }

    # Save back
    trade_data["finalPair"] = final_pair
    save_trade_json(trade_data)

    # FULL DASHBOARD 
    print("\n" + "="*70)
    print(f"Updated at: {datetime.now()}")
    print(f"LIVE CALL: ₹{call_price:.2f} | PUT: ₹{put_price:.2f}")
    print(f"SOLD TOTAL: ₹{total_sold_premium:.2f} → 40%: ₹{threshold_40_sold:.2f}")
    print(f"LIVE LOSS: ₹{live_loss:.2f} (Positive=Loss, Negative=Profit)")
    print("40% Distance:", forty_percent)

    
    if hedge_needed:
        print("HEDGE NEEDED: Nearest 5rs CALL+PUT BUY!")
    if add_new_option:
        print("ADD NEW: Same strike options!")
    if exit_strategy:
        print("STRATEGY EXIT: ₹1500 loss reached!")
    else:
        print("STRATEGY ACTIVE")
    print("="*70)


if __name__ == "__main__":
    update_premium_levels()