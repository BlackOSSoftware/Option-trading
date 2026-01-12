from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json
from datetime import datetime
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

app = FastAPI(title="Automated Option Strategy")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

TRADE_FILE = os.path.join(BASE_DIR, "storage", "trade.json")


def load_trade():
    try:
        with open(TRADE_FILE) as f:
            return json.load(f)
    except:
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
