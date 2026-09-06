#!/usr/bin/env python3
"""
Daily paper-trade capture.

Runs the live signal pipeline in dry-run mode and appends every generated
intent (approved or rejected) to `data/paper_trades.csv`.  After the trade
plays out, fill in the `exit_price` and `pnl` columns manually or via a
position monitor to measure live edge before risking capital.

Usage:
    source venv/bin/activate
    MASSIVE_API_KEY=... python scripts/paper_trade_daily.py

Recommended cron schedule: weekdays at 09:25 local (before the 9:30 open).
"""

import os
import sys
from datetime import datetime

# Ensure repo root is importable.
_RepoRoot = "/Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent"
if _RepoRoot not in sys.path:
    sys.path.insert(0, _RepoRoot)

from scripts.live_intents import main as live_main


def run() -> None:
    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print("WARNING: MASSIVE_API_KEY not set; Massive previous-close prices will be skipped.")

    # Build argv for live_intents.py so it runs in dry-run/paper mode.
    argv = [
        "scripts/live_intents.py",
        "--paper-trade-log", "data/paper_trades.csv",
    ]
    if api_key:
        argv.extend(["--massive-api-key", api_key])

    # Override sys.argv temporarily and run the live pipeline.
    old_argv = sys.argv
    sys.argv = argv
    try:
        live_main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    print(f"Paper-trade capture starting at {datetime.utcnow().isoformat()}Z")
    run()
    print("Done. Inspect data/paper_trades.csv for today's signals.")
