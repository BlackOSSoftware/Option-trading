import json
import requests
from typing import Dict, Any, List


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
        return abs(float(item.get("delta", 0.0)))
    except:
        return 0.0


# Find nearest delta option
def find_nearest_delta(options: List[Dict[str, Any]], target: float) -> Dict[str, Any]:
    if not options:
        return {}

    return min(options, key=lambda o: abs(get_delta(o) - target))


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


# Main
def fetch_option_greek() -> None:
    user = load_user_config()
    option = load_option_config()

    target_delta = float(option.get("delta", 0.20))

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

    chain = data.get("data", [])

    ce_list = [x for x in chain if x.get("optionType") == "CE"]
    pe_list = [x for x in chain if x.get("optionType") == "PE"]

    # FIND NEAREST DELTA OPTIONS
    nearest_ce = find_nearest_delta(ce_list, target_delta)
    nearest_pe = find_nearest_delta(pe_list, target_delta)

    final_pair = match_ce_pe(nearest_ce, nearest_pe)

    result = {
        "targetDelta": target_delta,
        "nearestCE": nearest_ce,
        "nearestPE": nearest_pe,
        "finalPair": final_pair
    }

    print("\n---- FINAL NEAREST DELTA RESULT ----\n")
    print(json.dumps(result, indent=4))

    save_trade_data(result)
    print("\nSaved to storage/trade.json")


if __name__ == "__main__":
    fetch_option_greek()
