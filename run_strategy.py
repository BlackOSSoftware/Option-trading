#!/usr/bin/env python3
"""
run_strategy.py

Master automation runner for Delta-based Option Selling Strategy

Flow:
1. Authenticate & validate session (auth.py)
2. Compute VWAP (spot / options) to determine market context
3. Select nearest delta options (option_greek1.py)
4. Execute paper/live trade (trade.py)
5. Persist everything into trade.json (single source of truth)

Run:
    python run_strategy.py
"""

import subprocess
import sys
import os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Helper to run scripts safely ----
def run_step(step_name: str, script_path: str):
    print(f"\n🚀 [{step_name}] Starting...")
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout:
            print(result.stdout)
        print(f"✅ [{step_name}] Completed")
    except subprocess.CalledProcessError as e:
        print(f"❌ [{step_name}] Failed")
        print(e.stderr)
        sys.exit(1)

# ---- Main Strategy Runner ----
def main():
    print("==========================================")
    print("📊 OPTION STRATEGY AUTOMATION STARTED")
    print(f"🕒 Time: {datetime.now().isoformat()}")
    print("==========================================")

    # 1️⃣ Auth & session validation
    run_step(
        "AUTHENTICATION",
        "services/auth.py"
    )

    # 2️⃣ Compute VWAP (context / regime)
    run_step(
        "VWAP COMPUTATION",
        "services/compute_vwap.py"
    )

    # 3️⃣ Delta-based option selection
    run_step(
        "DELTA OPTION SELECTION",
        "services/option_greek1.py"
    )

    # 4️⃣ Trade execution (paper / live)
    run_step(
        "TRADE EXECUTION",
        "services/trade.py"

    )

    print("==========================================")
    print("✅ STRATEGY EXECUTION COMPLETED SUCCESSFULLY")
    print("📁 Output saved in storage/trade.json")
    print("==========================================")

if __name__ == "__main__":
    main()
