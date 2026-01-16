import schedule
import time
import subprocess
import sys
from datetime import datetime

def is_market_open(now):
    if now.weekday() >= 5:  # Weekend
        return False
    market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    # Handle overnight runs
    if now.date() > market_end.date():
        return False
    return market_start <= now <= market_end

def run_strategy():
    now = datetime.now()
    if not is_market_open(now):
        print(f"⏹ Market closed at {now}")
        return
    try:
        result = subprocess.run(
            [sys.executable, "./run_strategy.py"], 
            cwd=".",  # Explicit cwd=backend/
            capture_output=True, 
            text=True, 
            check=True,
            timeout=120  # 2min timeout
        )
        print(f"✅ Strategy completed: {result.stdout[:200]}...")
    except subprocess.CalledProcessError as e:
        print(f"❌ Strategy failed: {e.stderr}")
    except subprocess.TimeoutExpired:
        print("❌ Strategy timed out (2min)")

# Run every weekday at 9:15 AM (initial trigger)
schedule.every().monday.at("09:15").do(run_strategy)
schedule.every().tuesday.at("09:15").do(run_strategy)
schedule.every().wednesday.at("09:15").do(run_strategy)
schedule.every().thursday.at("09:15").do(run_strategy)
schedule.every().friday.at("09:15").do(run_strategy)

# Optional: run every 5 minutes between 9:15 and 15:30 for live updates
schedule.every(5).minutes.do(run_strategy)

print("⏰ Scheduler started...")

while True:
    schedule.run_pending()
    time.sleep(1)
