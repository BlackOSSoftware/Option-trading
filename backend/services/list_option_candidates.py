# save as services/list_option_candidates.py
import os, json
from datetime import datetime
import requests

BASE_DIR = os.path.dirname(os.path.dirname(__file__))  
STORAGE = os.path.join(BASE_DIR, "storage")            
TRADE = os.path.join(STORAGE, "trade.json")
USER = os.path.join(STORAGE, "user.json")
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
SEARCH_SCRIP_URL = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/searchScrip"

def load(path):
    return json.load(open(path, "r", encoding="utf-8"))

def save(path, data):
    json.dump(data, open(path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)

trade = load(TRADE)
user = load(USER) if os.path.exists(USER) else {}

call = trade.get("finalPair", {}).get("call", {})
put = trade.get("finalPair", {}).get("put", {})

candidates = {}

def call_search(s):
    headers = {
        "X-PrivateKey": user.get("private_key",""),
        "Accept": "application/json",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": user.get("local_ip","127.0.0.1"),
        "X-ClientPublicIP": user.get("public_ip","127.0.0.1"),
        "X-MACAddress": user.get("mac_address","00:00:00:00:00:00"),
        "X-UserType": user.get("user_type","USER"),
        "Authorization": "Bearer " + (user.get("jwtToken") or user.get("feedToken","")),
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(SEARCH_SCRIP_URL, headers=headers, json={"exchange":"NFO","searchscrip":s}, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

for side,name in (("call",call),("put",put)):
    if not name:
        continue
    nm = name.get("name")
    exp = name.get("expiry")
    strike = name.get("strikePrice")
    opt = name.get("optionType")
    keys = [
        f"{nm}{exp}{int(float(strike))}{opt}",
        f"{nm}{int(float(strike))}{opt}",
        f"{nm}{strike}{opt}",
        nm
    ]
    found=[]
    for k in keys:
        res = call_search(k)
        found.append({"search":k,"result":res})
    candidates[side] = {"requested": name, "searches": found}

save(os.path.join(STORAGE, "option_candidates.json"), candidates)
print("Wrote storage/option_candidates.json — open and inspect candidate matches (look for token, expiry, strike).")
