# Automated Trading Engine
'''Added delta sign awareness (+ve for CE, −ve for PE).
Integrated live LTP fetching from Angel One API.
Introduced hedge selection (±5 strikes) with fallback logic.'''

import json
from unittest import result 
import requests
from typing import Dict, Any, List
from datetime import datetime


# Load user.json
def load_user_config() -> Dict[str, str]:
    with open("storage/user.json", "r") as file:
        return json.load(file)


# Load option.json
def load_option_config() -> Dict[str, Any]:
    with open("storage/option.json", "r") as file:
        return json.load(file)


# Save final result
def save_trade_data(data: Dict[str, Any]) -> None:
    with open("storage/trade.json", "w") as file:
        json.dump(data, file, indent=4)


# Convert delta safely
def get_delta(item: Dict[str, Any]) -> float:
    try:
        return float(item.get("delta", 0.0))
    except:
        return 0.0


# Find nearest delta option
def find_nearest_delta(options: List[Dict[str, Any]], target: float, opt_type: str) -> Dict[str, Any]:
    """
    Find option whose delta is closest to target.
    For CE, delta ~ +0.2 → target positive
    For PE, delta ~ -0.2 → target negative
    """
    if not options:
        return {}

    if opt_type == "PE":
        target = -abs(target)  # Ensure negative for puts
    else:
        target = abs(target)   # Positive for calls

    return min(options, key=lambda o: abs(get_delta(o) - target))


# Find Nearest 5 Rs Hedge Options
def find_nearest_5rs_hedge_options(chain: List[Dict], sold_strike: float, opt_type: str) -> List[Dict]:
    """
    Pick ±5 strike hedge options with correct delta sign.
    """
    hedges = []
    same_type = [x for x in chain if x.get("optionType") == opt_type]
    sold_strike_int = int(float(sold_strike))

    for option in same_type:
        strike = int(float(option.get("strikePrice", 0)))
        delta = get_delta(option)
        if opt_type == "PE" and delta > 0:
            continue  # skip positive delta puts
        if opt_type == "CE" and delta < 0:
            continue  # skip negative delta calls
        if strike == sold_strike_int - 5 or strike == sold_strike_int + 5:
            hedges.append({
                "strikePrice": option.get("strikePrice"),
                "ltp": float(option.get("ltp", 0)),
                "delta": delta,
                "optionType": opt_type,
                "tradingsymbol": option.get("tradingsymbol", "")
            })

    # fallback: pick closest strikes if ±5 not found
    if len(hedges) < 2:
        distances = []
        for option in same_type:
            strike = int(float(option.get("strikePrice", 0)))
            delta = get_delta(option)
            if opt_type == "PE" and delta > 0:
                continue
            if opt_type == "CE" and delta < 0:
                continue
            distances.append((abs(strike - sold_strike_int), option))
        distances.sort(key=lambda x: x[0])
        for _, option in distances[:2 - len(hedges)]:
            hedges.append({
                "strikePrice": option.get("strikePrice"),
                "ltp": float(option.get("ltp", 0)),
                "delta": get_delta(option),
                "optionType": opt_type,
                "tradingsymbol": option.get("tradingsymbol", "")
            })

    return hedges[:2]



# Match by nearest premium
def match_ce_pe(ce: Dict[str, Any], pe: Dict[str, Any]) -> Dict[str, Any]:
    if not ce or not pe:
        return {}
    ce_price = float(ce.get("ltp", 0.0))
    pe_price = float(pe.get("ltp", 0.0))
    return {
        "call": ce,
        "put": pe,
        "callPremium": ce_price,
        "putPremium": pe_price,
        "premiumDiff": abs(ce_price - pe_price)
    }


# Get LTP from Angel API (from tradeLevel.py)
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
        d = data.get("data") or {}
        ltp = float(d.get("ltp", 0.0))
        #print(f"LTP {tradingsymbol} ({token}) = {ltp}")
        return ltp
    except Exception as e:
        print("LTP exception:", e)
        return 0.0


# Find token from option_candidates.json
def find_token_from_candidates(name: str, expiry: str, strike: str, opt_type: str) -> str:
    """
    AUTO TOKENS - read from storage/option_candidates.json.
    No hard-coded 57003 / 57002.
    """
    strike_int = str(int(float(strike)))  # "26450"
    opt_type = opt_type.upper()

    try:
        with open("storage/option_candidates.json", "r") as f:
            candidates = json.load(f)  # built by list_option_candidates.py
    except Exception as e:
        print("Error loading option_candidates.json:", e)
        return ""

    expiry_key = expiry.replace("-", "").upper()
    short_expiry = expiry_key[:5]  # 30DEC, 23DEC, etc.

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

                #print(f"AUTO TOKEN MATCH: {ts} -> {token}")
                return token

    print(f"No token found for {name} {expiry} {strike_int}{opt_type}")
    return ""


# Main
def fetch_option_greek() -> None:
    user = load_user_config()
    option = load_option_config()
    
    url = "https://apiconnect.angelone.in/rest/secure/angelbroking/marketData/v1/optionGreek"
    headers = {
        "Authorization": f"Bearer {user['jwtToken']}",
        "Content-Type": "application/json",
        "Accept": user["accept"],
        "Accept-Encoding": user["accept_encoding"],
        "Connection": user["connection"],
        "X-PrivateKey": user["private_key"],
        "X-ClientLocalIP": user["local_ip"],
        "X-ClientPublicIP": user["public_ip"],
        "X-MACAddress": user["mac_address"],
        "X-UserType": user["user_type"],
        "X-SourceID": user["source_id"],
        "User-Agent": user["user_agent"]
    }
    body = {
        "name": option["name"],
        "expirydate": option["expirydate"]
    }
    response = requests.post(url, json=body, headers=headers)
    if response.status_code != 200:
        print("Failed:", response.text)
        return
    data = response.json()
    chain = data.get("data") or []

    print("Option chain length:", len(chain))

    ce_list = [x for x in chain if x.get("optionType") == "CE"]
    pe_list = [x for x in chain if x.get("optionType") == "PE"]

    # FIND NEAREST DELTA OPTIONS
    target_delta = float(option.get("delta", 0.20))
    nearest_ce = find_nearest_delta(ce_list, target_delta, "CE")
    nearest_pe = find_nearest_delta(pe_list, target_delta, "PE")

    atm_estimate = float(nearest_ce.get("strikePrice", 0)) - (target_delta * 5000)  # rough
    print(f"NIFTY spot ~{atm_estimate:.0f} | CE wing: {nearest_ce.get('strikePrice')} | PE wing: {nearest_pe.get('strikePrice')}")


    # Find TOKENS + LTP + SOLD POSITION
    print("Finding tokens + LTP...")
    call_token = find_token_from_candidates("NIFTY", option["expirydate"], nearest_ce.get("strikePrice", ""), "CE")
    put_token = find_token_from_candidates("NIFTY", option["expirydate"], nearest_pe.get("strikePrice", ""), "PE")

    print(f"CALL TOKEN: {call_token}")
    print(f"PUT TOKEN: {put_token}")

    call_ts = nearest_ce.get("tradingsymbol", "")
    put_ts = nearest_pe.get("tradingsymbol", "")

    call_ltp = get_ltp_from_angel(user, "NFO", call_ts, call_token) if call_token else 0.0
    put_ltp = get_ltp_from_angel(user, "NFO", put_ts, put_token) if put_token else 0.0

    # SOLD POSITION with LTP + TOKENS
    final_pair = {
        "call": {
            **nearest_ce,
            "symbolToken": call_token,
            "tradingsymbol": nearest_ce.get("tradingsymbol", ""),
            "ltp": call_ltp,
            "soldAt": datetime.now().isoformat()
        },
        "put": {
            **nearest_pe,
            "symbolToken": put_token,
            "tradingsymbol": nearest_pe.get("tradingsymbol", ""),
            "ltp": put_ltp,
            "soldAt": datetime.now().isoformat()
        },
        "callPremium": call_ltp,
        "putPremium": put_ltp,
        "premiumDiff": abs(call_ltp - put_ltp)
    }

    result = {
        "targetDelta": target_delta,
        "nearestCE": nearest_ce,
        "nearestPE": nearest_pe,
        "finalPair": final_pair,
        "positions": {
            "sold": {
                "call": {"strike": float(nearest_ce.get("strikePrice", 0)), "type": "CE", "ltp": call_ltp, "soldAt": datetime.now().isoformat()},
                "put": {"strike": float(nearest_pe.get("strikePrice", 0)), "type": "PE", "ltp": put_ltp, "soldAt": datetime.now().isoformat()}
            }
        }
    }

    # NEAREST 5 RS HEDGE OPTIONS (with LTP refresh)
    print("\nNEAREST 5 RS HEDGE OPTIONS:")

    # For CALL (26950CE → 26945CE, 26955CE)
    call_strike = float(nearest_ce.get("strikePrice", 0))
    hedge_ce_5rs = find_nearest_5rs_hedge_options(chain, call_strike, "CE")

    # Refresh LTP for hedge CE legs
    for hedge_ce in hedge_ce_5rs:
        strike = hedge_ce.get("strikePrice", "")
        token = find_token_from_candidates("NIFTY", option["expirydate"], strike, "CE")
        hedge_ce["symbolToken"] = token
        if token:
            hedge_ce["ltp"] = get_ltp_from_angel(user, "NFO", hedge_ce.get("tradingsymbol", ""), token)

    for hedge_ce in hedge_ce_5rs:
        strike = hedge_ce.get("strikePrice", "")
        delta = hedge_ce.get("delta", "")
        ltp = hedge_ce.get("ltp", 0)
        print(f" CALL 5Rs: {strike}CE (δ={delta}) → ₹{ltp:.2f}")

    # For PUT (25750PE → 25745PE, 25755PE)  
    put_strike = float(nearest_pe.get("strikePrice", 0))
    hedge_pe_5rs = find_nearest_5rs_hedge_options(chain, put_strike, "PE")

    # Refresh LTP for hedge PE legs
    for hedge_pe in hedge_pe_5rs:
        strike = hedge_pe.get("strikePrice", "")
        token = find_token_from_candidates("NIFTY", option["expirydate"], strike, "PE")
        hedge_pe["symbolToken"] = token
        if token:
                hedge_pe["ltp"] = get_ltp_from_angel(user, "NFO", hedge_pe.get("tradingsymbol", ""), token)

    for hedge_pe in hedge_pe_5rs:
        strike = hedge_pe.get("strikePrice", "")
        delta = hedge_pe.get("delta", "")
        ltp = hedge_pe.get("ltp", 0)
        print(f" PUT 5Rs: {strike}PE (δ={delta}) → ₹{ltp:.2f}")

    # SAVE HEDGE OPTIONS TO trade.json
    result["hedgeOptions"] = {
        "call_5rs": hedge_ce_5rs,
        "put_5rs": hedge_pe_5rs,
        "hedgeCost": sum(float(x.get("ltp", 0)) for x in hedge_ce_5rs) +
                     sum(float(x.get("ltp", 0)) for x in hedge_pe_5rs)
    }

    print(f"TOTAL HEDGE COST: ₹{result['hedgeOptions']['hedgeCost']:.2f}")
    print("\n---- FINAL NEAREST DELTA + SOLD POSITION ----\n")
    print(json.dumps(result, indent=4))
    save_trade_data(result)
    print("\nSOLD POSITION SAVED with TOKENS + LTP!")


if __name__ == "__main__":
    fetch_option_greek()
