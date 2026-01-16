from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json
from datetime import datetime
import os

# backend directory
BACKEND_DIR = os.path.dirname(__file__)

# project root directory
BASE_DIR = os.path.dirname(BACKEND_DIR)

app = FastAPI(title="Automated Option Strategy")

# templates are in project root
templates = Jinja2Templates(
    directory=os.path.join(BASE_DIR, "templates")
)

# static is in project root
app.mount(
    "/static",
    StaticFiles(directory=os.path.join(BASE_DIR, "static")),
    name="static"
)

# trade.json is in backend/storage
TRADE_FILE = os.path.join(BACKEND_DIR, "storage", "trade.json")


def load_trade():
    try:
        with open(TRADE_FILE) as f:
            data = json.load(f)
            return data
    except Exception as e:
        print("Failed to load trade.json:", e)
        return {}


@app.get("/")
def dashboard(request: Request):
    trade = load_trade()

    final = trade.get("finalPair", {})
    call = final.get("call", {})
    put = final.get("put", {})

    context = {
        "request": request,
        "time": datetime.now().strftime("%H:%M:%S"),
        "trade": trade,
        "call": call,
        "put": put,
    }

    return templates.TemplateResponse("dashboard.html", context)
