import json
import requests
from datetime import datetime
from typing import TypedDict


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
    with open("../storage/user.json", "r") as f:
        return json.load(f)


# ---------------------------
# Load trade.json (Correct Path)
# ---------------------------
def load_trade_json() -> dict:
    with open("../storage/trade.json", "r") as f:
        return json.load(f)


# ---------------------------
# Save trade.json (Correct Path)
# ---------------------------
def save_trade_json(data: dict) -> None:
    with open("../storage/trade.json", "w") as f:
        json.dump(data, f, indent=4)


# -----------------------------------------
# SAFE Angel Broking LTP Fetch Function
# -----------------------------------------
def get_ltp_from_angel(user: dict, token: str) -> float:
    url = "https://apiconnect.angelone.in/rest/secure/market/v1/quote/"
    headers = {
        "Authorization": f"Bearer {user['jwtToken']}",
        "X-PrivateKey": user["private_key"],
        "X-UserType": user["user_type"],
        "X-SourceID": user["source_id"],
        "X-ClientLocalIP": user["local_ip"],
        "X-ClientPublicIP": user["public_ip"],
        "X-MACAddress": user["mac_address"],
        "X-UserID": user["clientcode"],
        "Content-Type": "application/json"
    }

    payload = {
        "mode": "FULL",
        "exchangeTokens": {
            "NFO": [token]
        }
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception as e:
        print("Error calling Angel API:", e)
        return 0.0

    if r.status_code != 200:
        print("Angel API Error:", r.text)
        return 0.0

    try:
        data = r.json()
    except:
        print("Invalid JSON:", r.text)
        return 0.0

    try:
        return float(data["data"]["fetched"][0]["ltp"])
    except:
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

    # Fetch Premiums
    call_price = get_ltp_from_angel(user, call_token)
    put_price = get_ltp_from_angel(user, put_token)

    total = call_price + put_price
    forty_percent = round(total * 0.40, 2)

    # Update values
    final_pair["callPremium"] = call_price
    final_pair["putPremium"] = put_price
    final_pair["premiumDiff"] = abs(call_price - put_price)
    final_pair["distance"] = forty_percent

    # Save back
    trade_data["finalPair"] = final_pair
    save_trade_json(trade_data)

    print("Updated at:", datetime.now())
    print("CALL:", call_price, "| PUT:", put_price)
    print("40% Distance:", forty_percent)


# Run
update_premium_levels()
