#!/usr/bin/env python3
"""
services/compute_vwap.py

Robust VWAP computation for call & put:
- Finds symboltoken from option.json, option_candidates.json, local scripmaster, or SearchScrip API
- Fetches historical candles from AngelOne getCandleData
- Computes VWAP and compares to last close -> writes results into storage/trade.json
- Saves raw candle data to storage/candles/<symboltoken>.json for debugging
- Writes vwapFailureReason when VWAP cannot be computed

Usage:
    pip install requests
    python services/compute_vwap.py
"""

from __future__ import annotations
import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
import math

try:
    import requests
except Exception:
    raise SystemExit("Please install requests: pip install requests")

# ---- Config ----
ANGEL_CANDLE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
SEARCH_SCRIP_URL = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/searchScrip"
SCRIP_MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

HTTP_TIMEOUT = 20
RETRIES = 2
BACKOFF_FACTOR = 1.0  # seconds

# ---- Paths ----
BASE_DIR = os.path.dirname(os.path.dirname(__file__))  
STORAGE_DIR = os.path.join(BASE_DIR, "storage")        

TRADE_JSON_PATH = os.path.join(STORAGE_DIR, "trade.json")
USER_JSON_PATH = os.path.join(STORAGE_DIR, "user.json")
OPTION_JSON_PATH = os.path.join(STORAGE_DIR, "option.json")
CANDIDATES_PATH = os.path.join(STORAGE_DIR, "option_candidates.json")
SCRIPMASTER_PATH = os.path.join(STORAGE_DIR, "scripmaster.json")
CANDLES_DIR = os.path.join(STORAGE_DIR, "candles")

os.makedirs(CANDLES_DIR, exist_ok=True)

# ---- Simple JSON helpers ----
def load_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[load_json] failed to read {path}: {e}")
        return None

def save_json(path: str, data: Any):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ---- Normalizers & token matching ----
def normalize_expiry(expiry: Optional[str]) -> Optional[str]:
    """
    Normalize expiry to YYYY-MM-DD
    Accepts: 30DEC2025, 30-Dec-2025, 2025-12-30
    """
    if not expiry:
        return None

    e = str(expiry).strip().upper()

    # Already ISO format
    try:
        return datetime.strptime(e, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        pass

    # 30DEC2025
    try:
        return datetime.strptime(e, "%d%b%Y").strftime("%Y-%m-%d")
    except:
        pass

    # 30-DEC-2025
    try:
        return datetime.strptime(e, "%d-%b-%Y").strftime("%Y-%m-%d")
    except:
        pass

    return None

def build_symbol_variants(name: str, expiry: str, strike: str, opt_type: str) -> List[str]:
    variants: List[str] = []
    e = normalize_expiry(expiry) or ""
    try:
        strike_i = str(int(float(strike)))
    except Exception:
        strike_i = str(strike)
    # Useful patterns seen in scrip masters
    variants.append(f"{name}{e}{strike_i}{opt_type}")
    variants.append(f"{name}{strike_i}{opt_type}")
    variants.append(f"{name}{opt_type}{strike_i}")
    variants.append(f"{name}{e}{strike_i}")
    variants.append(f"{name}{strike_i}")
    variants.append(f"{strike_i}{opt_type}")
    variants += [v.lower() for v in variants]
    # remove duplicates preserving order
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out

def normalize_strike(val) -> Optional[float]:
    try:
        return round(float(val), 2)
    except:
        return None

def find_token_from_entries(entries: List[dict], name: str, expiry: str, strike: str, opt_type: str) -> Optional[str]:
    if not entries:
        return None

    variants = build_symbol_variants(name, expiry, strike, opt_type)
    target_strike = None
    try:
        target_strike = float(strike)
    except Exception:
        target_strike = strike

    name_up = str(name).strip().upper()

    for ent in entries:
        try:
            trad = (ent.get("tradingsymbol") or ent.get("symbol") or ent.get("scrip") or ent.get("name") or "").upper()
            token = ent.get("symboltoken") or ent.get("token") or ent.get("instrumentToken") or ent.get("tokenId") or ent.get("token_id")
            if not trad or not token:
                continue

            # First try symbol variants match
            for v in variants:
                if v.upper() in trad:
                    return str(token)

            # fallback: strike + option type + expiry
            ent_str = normalize_strike(ent.get("strike") or ent.get("strikePrice") or ent.get("strike_price"))
            target_strike_n = normalize_strike(target_strike)
            ent_opt = (ent.get("optionType") or ent.get("instrumenttype") or ent.get("type") or "").upper()

            if ent_str is not None and target_strike_n is not None:
                if ent_str == target_strike_n:
                    if opt_type and opt_type.upper() in ent_opt:
                        return str(token)
                    # still return token if strike matches even if option type doesn't
                    return str(token)

        except Exception:
            continue

    return None


# ---- Token discovery pipeline ----
def pick_auth_token(user_json: Optional[dict]) -> Optional[str]:
    if not user_json:
        return None
    for k in ("feedToken", "feed_token", "feed", "historyToken"):
        if user_json.get(k):
            return user_json.get(k)
    return user_json.get("jwtToken") or user_json.get("token") or user_json.get("jwt")

def build_headers(user_json: Optional[dict]) -> dict:
    u = user_json or {}
    auth_val = pick_auth_token(u)
    return {
        "X-PrivateKey": u.get("private_key", ""),
        "Accept": "application/json",
        "X-SourceID": u.get("source_id", "WEB"),
        "X-ClientLocalIP": u.get("local_ip", "127.0.0.1"),
        "X-ClientPublicIP": u.get("public_ip", "127.0.0.1"),
        "X-MACAddress": u.get("mac_address", "00:00:00:00:00:00"),
        "X-UserType": u.get("user_type", "USER"),
        "Authorization": f"Bearer {auth_val}" if auth_val else "",
        "Content-Type": "application/json",
    }

def try_find_token(name: str, expiry: str, strike: str, opt_type: str, user_json: Optional[dict]) -> Tuple[Optional[str], str]:
    """
    Returns (token_or_None, source_str)
    source_str indicates where token was found (option.json, candidates, scripmaster, searchScrip, none)
    """
    # 1) option.json
    option_json = load_json(OPTION_JSON_PATH)
    if option_json:
        # normalize to list of dicts
        entries = option_json if isinstance(option_json, list) else [v for v in option_json.values() if isinstance(v, dict)]
        token = find_token_from_entries(entries, name, expiry, strike, opt_type)
        if token:
            return token, "option.json"

    # 2) option_candidates.json (uploaded large list)
    candidates = load_json(CANDIDATES_PATH)
    if candidates:
        # candidates may be dict or list
        entries = None
        if isinstance(candidates, list):
            entries = candidates
        elif isinstance(candidates, dict):
            # check for top-level key with list
            for k in ("data", "result", "scrips", "list"):
                if k in candidates and isinstance(candidates[k], list):
                    entries = candidates[k]
                    break
            if entries is None:
                entries = [v for v in candidates.values() if isinstance(v, dict)]
        if entries:
            token = find_token_from_entries(entries, name, expiry, strike, opt_type)
            if token:
                return token, "option_candidates.json"

    # 3) local scripmaster file (if downloaded)
    sm = load_json(SCRIPMASTER_PATH)
    if sm:
        entries = None
        if isinstance(sm, list):
            entries = sm
        elif isinstance(sm, dict):
            for k in ("data", "result", "scrips"):
                if k in sm and isinstance(sm[k], list):
                    entries = sm[k]
                    break
            if entries is None:
                entries = [v for v in sm.values() if isinstance(v, dict)]
        if entries:
            token = find_token_from_entries(entries, name, expiry, strike, opt_type)
            if token:
                return token, "local_scripmaster"

    # 4) SearchScrip API fallback (if user_json present)
    if user_json:
        # try a few search strings
        candidates_list = []
        try:
            strike_i = int(float(strike))
            candidates_list += [
                f"{name}{normalize_expiry(expiry)}{strike_i}{opt_type}",
                f"{name}{strike_i}{opt_type}",
                f"{name}{opt_type}{strike_i}",
            ]
        except Exception:
            candidates_list.append(f"{name}{strike}{opt_type}")
        candidates_list.append(name)
        for s in candidates_list:
            try:
                headers = build_headers(user_json)
                payload = {"exchange": "NFO", "searchscrip": s}
                r = requests.post(SEARCH_SCRIP_URL, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                if isinstance(j, dict) and j.get("data"):
                    entries = j.get("data")
                    token = find_token_from_entries(entries, name, expiry, strike, opt_type)
                    if token:
                        return token, f"searchScrip:{s}"
            except Exception:
                continue

    return None, "none"

# ---- Candle fetch, save raw response ----
def save_raw_candles(token: str, payload: dict, response_json: Any):
    fname = os.path.join(CANDLES_DIR, f"{token}.json")
    content = {"fetched_at": datetime.now().isoformat(), "request": payload, "response": response_json}
    save_json(fname, content)

def fetch_candles_for_token(symboltoken: str, user_json: Optional[dict], interval: str, from_dt: datetime, to_dt: datetime) -> Optional[List[List]]:
    payload = {
        "exchange": "NFO" if str(symboltoken).isdigit() else "NSE",
        "symboltoken": str(symboltoken),
        "interval": interval,
        "fromdate": from_dt.strftime("%Y-%m-%d %H:%M"),
        "todate": to_dt.strftime("%Y-%m-%d %H:%M"),
    }
    headers = build_headers(user_json or {})
    for attempt in range(RETRIES + 1):
        try:
            r = requests.post(ANGEL_CANDLE_URL, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
            # Try to parse JSON
            try:
                j = r.json()
            except Exception:
                # save non-json raw and return None
                save_raw_candles(symboltoken, payload, {"non_json_response": r.text[:1000], "status_code": r.status_code})
                return None
            # Save raw response for auditing
            save_raw_candles(symboltoken, payload, j)
            # If status true and data present (could be empty list)
            if isinstance(j, dict) and (j.get("status") or j.get("success")):
                return j.get("data") or []
            # If API returned success=false or error message, return None but keep raw
            return None
        except Exception as e:
            print(f"[fetch_candles_for_token] attempt {attempt} error: {e}")
            time.sleep(BACKOFF_FACTOR * (attempt + 1))
    return None

def load_candles_from_file(token: str) -> Optional[List[List]]:
    path = os.path.join(CANDLES_DIR, f"{token}.json")
    j = load_json(path)
    if j and "response" in j and "data" in j["response"]:
        return j["response"]["data"]
    return None

# ---- VWAP compute ----
def compute_vwap_from_candles(candles: List[List]) -> Optional[float]:
    if not candles:
        return None
    num = 0.0
    den = 0.0
    for c in candles:
        try:
            high = float(c[2])
            low = float(c[3])
            close = float(c[4])
            vol = float(c[5]) if len(c) > 5 else 0.0
            tp = (high + low + close) / 3.0
            num += tp * vol
            den += vol
        except Exception:
            continue
    if den == 0.0 or math.isclose(den, 0.0):
        return None
    return num / den

def last_close_from_candles(candles: List[List]) -> Optional[float]:
    if not candles:
        return None
    for c in reversed(candles):
        try:
            return float(c[4])
        except Exception:
            continue
    return None

def build_tradingsymbol(name: str, expiry: str, strike: str, opt_type: str) -> str:
    """
    Build Angel One tradingsymbol
    Example: NIFTY13JAN26CE26650
    """
    if not (name and expiry and strike and opt_type):
        return ""

    exp = str(expiry).replace("-", "").upper()
    try:
        strike_i = str(int(float(strike)))
    except Exception:
        strike_i = str(strike)

    return f"{name}{exp}{opt_type.upper()}{strike_i}"

# ---- Per-instrument processing ----
def process_instrument(side_obj: dict, user_json: Optional[dict]) -> Dict[str, Any]:
    """
    Returns a dict with keys:
      vwap (float or None), vwapStatus (upar/niche/unknown), vwapFailureReason (when unknown), usedToken, tokenSource
    """
    result = {"vwap": None, "vwapStatus": "unknown", "vwapFailureReason": None, "usedToken": None, "tokenSource": None}
    if not side_obj:
        result["vwapFailureReason"] = "no_instrument"
        return result

    name = side_obj.get("name")
    expiry = side_obj.get("expiry")
    strike = side_obj.get("strikePrice") or side_obj.get("strike")
    opt_type = (side_obj.get("optionType") or "").upper()

    # 1) Find token
    token = side_obj.get("symbolToken")
    if token:
        src = "trade.json"
    else:
        token, src = try_find_token(name, expiry, strike, opt_type, user_json)
    result["usedToken"] = token
    result["tokenSource"] = src

    if not token:
        result["vwapFailureReason"] = "token_not_found"
        
        return result
    
    # Populate tradingsymbol if missing
    if token and not side_obj.get("tradingsymbol"):
        side_obj["tradingsymbol"] = build_tradingsymbol(
            name=name,
            expiry=expiry,
            strike=strike,
            opt_type=opt_type
        )

    # 2) Try local candles first, then API
    now = datetime.now()
    # today market hours
    from_dt = now.replace(hour=9, minute=15, second=0, microsecond=0)
    to_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if from_dt > now:
        # market not open today -> fallback to last 60 minutes
        from_dt = now - timedelta(minutes=60)
        to_dt = now

    # LOAD LOCAL FIRST
    candles = load_candles_from_file(token)
    if candles is None or len(candles) == 0:
        # fallback to API
        candles = fetch_candles_for_token(token, user_json, "ONE_MINUTE", from_dt, to_dt)
        if candles is None:
            # Attempt previous trading day full range
            prev = now - timedelta(days=1)
            prev_from = prev.replace(hour=9, minute=15, second=0, microsecond=0)
            prev_to = prev.replace(hour=15, minute=30, second=0, microsecond=0)
            candles = fetch_candles_for_token(token, user_json, "ONE_MINUTE", prev_from, prev_to)
        if candles is None:
            # Attempt 3: hourly over last 30 days
            to_dt2 = now
            from_dt2 = now - timedelta(days=30)
            candles = fetch_candles_for_token(token, user_json, "ONE_HOUR", from_dt2, to_dt2)

    if candles is None:
        result["vwapFailureReason"] = "api_error_or_nonjson"
        return result

    if isinstance(candles, list) and len(candles) == 0:
        result["vwapFailureReason"] = "no_candles"
        return result

    vwap = compute_vwap_from_candles(candles)
    last_close = last_close_from_candles(candles)
    if vwap is None or last_close is None:
        result["vwapFailureReason"] = "no_volume_or_bad_candles"
        return result

    result["vwap"] = round(vwap, 6)
    result["vwapStatus"] = "Above" if vwap > last_close else "Below"
    result["vwapFailureReason"] = None

    return result

# ---- Main ----
def main():
    trade = load_json(TRADE_JSON_PATH)
    if not trade:
        print(f"[main] trade.json not found at {TRADE_JSON_PATH}. Aborting.")
        return

    user_json = load_json(USER_JSON_PATH) or {}
    
    # Attempt token discovery uses files and API as needed
    final = trade.setdefault("finalPair", {})
    call_obj = final.setdefault("call", {})
    put_obj = final.setdefault("put", {})

    print("[main] processing CALL...")
    call_res = process_instrument(call_obj, user_json)
    print("[main] processing PUT...")
    put_res = process_instrument(put_obj, user_json)

    for key in ("vwap", "vwapStatus", "vwapFailureReason", "usedToken", "tokenSource"):
        if key in call_res:
            call_obj[key] = call_res[key]

        if key in put_res:
            put_obj[key] = put_res[key]
    
    trade["vwapSummary"] = {
        "call": {
            "vwap": call_obj.get("vwap"),
            "status": call_obj.get("vwapStatus"),
        },
        "put": {
            "vwap": put_obj.get("vwap"),
            "status": put_obj.get("vwapStatus"),
        },
        "computed_at": datetime.now().isoformat(),
    }

    save_json(TRADE_JSON_PATH, trade)
    print(f"[main] VWAP computation done. Results saved to storage/trade.json")

if __name__ == "__main__":
    main()
