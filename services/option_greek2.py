# Quant Engine
'''Introduced Black–Scholes delta for theoretical validation.
Calculated market-derived spot, IV, and days to expiry.
Strike selection based on min(|BS_delta − target_delta|), not just API values.'''

import json
import requests
import re
from math import log, sqrt
from scipy.stats import norm
from typing import Dict, Any, List
from datetime import datetime

# ==============================
# CONFIG LOADING / SAVING
# ==============================
def load_user_config() -> Dict[str, str]:
    with open("storage/user.json", "r") as file:
        return json.load(file)

def load_option_config() -> Dict[str, Any]:
    with open("storage/option.json", "r") as file:
        return json.load(file)

def save_trade_data(data: Dict[str, Any]) -> None:
    with open("storage/trade.json", "w") as file:
        json.dump(data, file, indent=4)

# ==============================
# BLACK–SCHOLES DELTA (for sanity check only)
# ==============================
def bs_delta(spot: float, strike: float, days_to_expiry: int, option_type: str, iv: float, r: float = 0.07) -> float:
    if days_to_expiry <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
        return 0.0
    T = days_to_expiry / 365.0
    d1 = (log(spot / strike) + (r + 0.5 * iv ** 2) * T) / (iv * sqrt(T))
    return norm.cdf(d1) if option_type == "CE" else norm.cdf(d1) - 1

def get_delta_per_strike(item, spot, days):
    if "delta" in item and float(item["delta"]) != 0:
        return float(item["delta"])
    # fallback to BS delta if not available
    iv = float(item.get("impliedVolatility", item.get("iv", 15))) / 100
    return bs_delta(spot=spot, strike=float(item["strikePrice"]), days_to_expiry=days, option_type=item["optionType"], iv=iv)


# ==============================
# MARKET INPUTS
# ==============================
def parse_expiry_date(expiry: str):
    s = re.sub(r'[^0-9A-Z]', '', expiry.upper()).replace("W", "")
    for fmt in ("%d%b%y", "%d%b%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    raise ValueError("Invalid expiry format")

def get_spot_from_chain(chain):
    for row in chain:
        uv = row.get("underlyingValue")
        if uv and float(uv) > 0:
            return float(uv)
    strikes = [float(x.get("strikePrice", 0)) for x in chain if x.get("strikePrice")]
    return round(sum(strikes)/len(strikes)) if strikes else 25000

def get_market_inputs(chain: List[Dict], expiry: str):
    spot = get_spot_from_chain(chain)
    ivs = [float(x.get("impliedVolatility", x.get("iv", 0)))/100
           for x in chain if 5 < float(x.get("impliedVolatility", x.get("iv", 0))) < 100]
    avg_iv = sum(ivs)/len(ivs) if ivs else 0.15
    expiry_dt = parse_expiry_date(expiry)
    days = max((expiry_dt - datetime.now().date()).days, 1)
    print(f"Market → Spot={spot}, Avg IV={avg_iv:.2%}, Days={days}")
    return spot, avg_iv, days

# ==============================
# FINAL STRIKE-BASED ENGINE
# ==============================
def round_to_strike(spot: float, step: int = 50) -> int:
    return int(round(spot / step) * step)

def find_nearest_delta(chain: list, spot: float, days: int, target_delta=0.20):
    """
    Finds CE and PE strikes closest to the target delta (0.20 for straddle)
    """
    # Filter CE and PE options
    ce_options = [x for x in chain if x.get("optionType") == "CE"]
    pe_options = [x for x in chain if x.get("optionType") == "PE"]

    # Find CE strike closest to +0.20 delta
    ce_target = min(ce_options, key=lambda x: abs(get_delta_per_strike(x, spot, days) - target_delta))
    
    # Find PE strike closest to -0.20 delta (use absolute value)
    pe_target = min(pe_options, key=lambda x: abs(abs(get_delta_per_strike(x, spot, days)) - target_delta))
    
    return ce_target, pe_target


# ==============================
# TOKEN & LTP HANDLING
# ==============================
def find_token_from_candidates(name: str, expiry: str, strike: str, opt_type: str) -> str:
    strike_int = str(int(float(strike)))
    opt_type = opt_type.upper()
    try:
        with open("storage/option_candidates.json", "r") as f:
            candidates = json.load(f)
    except Exception as e:
        print("Error loading option_candidates.json:", e)
        return ""

    expiry_key = expiry.replace("-", "").upper()
    short_expiry = expiry_key[:5]

    for side in candidates.values():
        for search_res in side.get("searches", []):
            data = (search_res.get("result") or {}).get("data") or []
            for row in data:
                ts = str(row.get("tradingsymbol", "")).upper()
                token = str(row.get("symboltoken", ""))
                if name.upper() not in ts:
                    continue
                if opt_type not in ts:
                    continue
                if strike_int not in ts:
                    continue
                if short_expiry not in ts and expiry_key not in ts:
                    continue
                return token
    print(f"No token found for {name} {expiry} {strike_int}{opt_type}")
    return ""

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
    payload = {"exchange": exchange, "tradingsymbol": tradingsymbol, "symboltoken": token}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        d = data.get("data") or {}
        return float(d.get("ltp", 0.0))
    except Exception as e:
        print("LTP exception:", e)
        return 0.0

# ==============================
# HEDGE OPTIONS
# ==============================
def find_nearest_5rs_hedge_options(chain: List[Dict], sold_strike: float, opt_type: str, user: dict, expiry: str, spot: float, days_to_expiry: int) -> List[Dict]:
    same_type = [x for x in chain if x.get("optionType") == opt_type]
    sold_strike_int = int(round(sold_strike))
    distances = [(abs(int(float(o.get("strikePrice", 0))) - sold_strike_int), o)
                 for o in same_type if int(float(o.get("strikePrice", 0))) != sold_strike_int]
    distances.sort(key=lambda x: x[0])
    closest = distances[:2]
    hedges = []
    for _, h in closest:
        ts = h.get("tradingsymbol", "")
        token = find_token_from_candidates("NIFTY", expiry, h.get("strikePrice", ""), opt_type)
        ltp = get_ltp_from_angel(user, "NFO", ts, token) if token else 0.0
        hedges.append({
            "strikePrice": h.get("strikePrice"),
            "ltp": ltp,
            "delta": get_delta_per_strike(h, spot, days_to_expiry),
            "optionType": opt_type,
            "tradingsymbol": ts,
            "symbolToken": token
        })
    return hedges[:2]

# ==============================
# MAIN ENGINE
# ==============================
def fetch_option_greek() -> None:
    user = load_user_config()
    option = load_option_config()
    url = "https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/optionGreek"
    headers = {
        "Authorization": f"Bearer {user['jwtToken']}",
        "Content-Type": "application/json",
        "Accept": user["accept"],
        "X-PrivateKey": user["private_key"],
        "X-ClientLocalIP": user["local_ip"],
        "X-ClientPublicIP": user["public_ip"],
        "X-MACAddress": user["mac_address"],
        "X-UserType": user["user_type"],
        "X-SourceID": user["source_id"],
        "User-Agent": user["user_agent"]
    }
    body = {"name": option["name"], "expirydate": option["expirydate"]}
    response = requests.post(url, json=body, headers=headers)
    if response.status_code != 200:
        print("Failed:", response.text)
        return

    data = response.json()
    chain = data.get("data") or []
    print("Option chain length:", len(chain))
    target_delta = 0.20

    underlying, avg_iv, days_to_expiry = get_market_inputs(chain, option["expirydate"])

    # ==============================
    # FINAL STRIKE SELECTION
    # ==============================

    # === Find nearest 0.20-delta CE and PE ===
    nearest_ce, nearest_pe = find_nearest_delta(chain, spot=underlying, days=days_to_expiry, target_delta=0.20)

    ce_strike = float(nearest_ce["strikePrice"])
    pe_strike = float(nearest_pe["strikePrice"])

    ce_list = [x for x in chain if x.get("optionType") == "CE"]
    pe_list = [x for x in chain if x.get("optionType") == "PE"]

    nearest_ce = next(x for x in ce_list if float(x.get("strikePrice", 0)) == ce_strike)
    nearest_pe = next(x for x in pe_list if float(x.get("strikePrice", 0)) == pe_strike)

    print(f"FINAL STRIKES → CE={ce_strike}, PE={pe_strike}")
    print(f"BS Sanity → CE Δ={get_delta_per_strike(nearest_ce, underlying, days_to_expiry):.3f}, PE Δ={get_delta_per_strike(nearest_pe, underlying, days_to_expiry):.3f}")

    # ==============================
    # GET TOKENS + LTP
    # ==============================
    call_token = find_token_from_candidates("NIFTY", option["expirydate"], ce_strike, "CE")
    put_token = find_token_from_candidates("NIFTY", option["expirydate"], pe_strike, "PE")

    call_ts = nearest_ce.get("tradingsymbol", "")
    put_ts = nearest_pe.get("tradingsymbol", "")

    call_ltp = get_ltp_from_angel(user, "NFO", call_ts, call_token) if call_token else 0.0
    put_ltp = get_ltp_from_angel(user, "NFO", put_ts, put_token) if put_token else 0.0

    final_pair = {
        "call": {**nearest_ce, "symbolToken": call_token, "tradingsymbol": call_ts, "ltp": call_ltp, "soldAt": datetime.now().isoformat()},
        "put": {**nearest_pe, "symbolToken": put_token, "tradingsymbol": put_ts, "ltp": put_ltp, "soldAt": datetime.now().isoformat()},
        "callPremium": call_ltp,
        "putPremium": put_ltp,
        "premiumDiff": abs(call_ltp - put_ltp)
    }

    # ==============================
    # FIND HEDGE OPTIONS
    # ==============================
    hedge_ce_5rs = find_nearest_5rs_hedge_options(chain, ce_strike, "CE", user, option["expirydate"], underlying, days_to_expiry)
    hedge_pe_5rs = find_nearest_5rs_hedge_options(chain, pe_strike, "PE", user, option["expirydate"], underlying, days_to_expiry)

    result = {
    "targetDelta": target_delta,
    "nearestCE": nearest_ce,
    "nearestPE": nearest_pe,
    "finalPair": final_pair,
    "positions": {
        "sold": {
            "call": {"strike": ce_strike, "type": "CE", "ltp": call_ltp, "soldAt": datetime.now().isoformat()},
            "put": {"strike": pe_strike, "type": "PE", "ltp": put_ltp, "soldAt": datetime.now().isoformat()}
        }
    },
    "spot": underlying,
    "atm": round_to_strike(underlying),
    "selectedStrikes": {"CE": ce_strike, "PE": pe_strike},
    "hedgeOptions": {
        "call_5rs": hedge_ce_5rs,
        "put_5rs": hedge_pe_5rs,
        "hedgeCost": sum(x["ltp"] for x in hedge_ce_5rs + hedge_pe_5rs)
    }
}


    save_trade_data(result)
    print(f"\nFINAL RESULT SAVED → TOTAL HEDGE COST ₹{result['hedgeOptions']['hedgeCost']:.2f}")
    print(json.dumps(result, indent=4))

# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    fetch_option_greek()
