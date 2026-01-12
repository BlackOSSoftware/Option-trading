import schedule
import time
import subprocess
import sys
from datetime import datetime

def run_strategy():
    print(f"🚀 Strategy triggered at {datetime.now()}")
    subprocess.run([sys.executable, "run_strategy.py"])

# Run every trading day at 9:15 AM
schedule.every().monday.at("09:15").do(run_strategy)
schedule.every().tuesday.at("09:15").do(run_strategy)
schedule.every().wednesday.at("09:15").do(run_strategy)
schedule.every().thursday.at("09:15").do(run_strategy)
schedule.every().friday.at("09:15").do(run_strategy)

print("⏰ Scheduler started... Waiting for 9:15 AM")

while True:
    schedule.run_pending()
    time.sleep(1)
