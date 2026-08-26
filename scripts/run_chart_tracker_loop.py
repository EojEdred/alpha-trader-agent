#!/usr/bin/env python3
"""
Standalone Chart Tracker Loop for TopstepX futures.

Usage:
    # Signal-only mode (recommended for testing)
    venv/bin/python scripts/run_chart_tracker_loop.py --symbol NQ

    # Dry-run execution mode (orders simulated through ProjectX API)
    venv/bin/python scripts/run_chart_tracker_loop.py --symbol NQ --execute

    # One-shot analysis
    venv/bin/python scripts/run_chart_tracker_loop.py --symbol NQ --once

This script is intentionally separate from the APScheduler so it can be run
manually, supervised, or wrapped by a cron/systemd task. It respects the same
.env safety gates as the main scheduler (TOPSTEP_DRY_RUN,
TOPSTEP_TRADING_ENABLED, TOPSTEP_ORDER_CONFIRMATION).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger

# Add repo root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.topstep_chart_tracker import run_chart_tracker_cycle, run_chart_tracker_loop


def _configure_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "chart_tracker.log",
        rotation="1 day",
        retention="14 days",
        level="INFO",
    )
    logger.add(
        log_dir / "chart_tracker_signals.log",
        rotation="1 day",
        retention="30 days",
        level="INFO",
        filter=lambda record: "signal" in record["message"].lower() or record["level"].name == "INFO",
    )


async def _once(symbol: str, execute: bool = False):
    result = await run_chart_tracker_cycle(symbol=symbol, execute=execute)
    signal = result.get("signal", {})
    print(f"[{result.get('timestamp')}] {symbol}")
    print(f"  direction: {signal.get('direction', 'none')}")
    print(f"  score:     {signal.get('score', 0)}")
    print(f"  entry:     {signal.get('entry_price')}")
    print(f"  stop:      {signal.get('stop_loss')}")
    print(f"  target:    {signal.get('take_profit')}")
    print(f"  executed:  {result.get('executed')}")
    if result.get("execution_result"):
        print(f"  execution: {result['execution_result'].get('status')}")
    return result


async def main():
    parser = argparse.ArgumentParser(description="TopstepX Chart Tracker Loop")
    parser.add_argument("--symbol", default="NQ", help="Futures symbol to track")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between cycles")
    parser.add_argument("--execute", action="store_true", help="Place orders (still gated by .env)")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--max-iterations", type=int, default=None, help="Max cycles before exit")
    args = parser.parse_args()

    _configure_logging(ROOT / "logs")

    dry_run = os.getenv("TOPSTEP_DRY_RUN", "true").lower() == "true"
    trading_enabled = os.getenv("TOPSTEP_TRADING_ENABLED", "false").lower() == "true"

    logger.info(
        f"Chart tracker CLI start: symbol={args.symbol} execute={args.execute} "
        f"dry_run={dry_run} trading_enabled={trading_enabled}"
    )

    if args.execute and not trading_enabled:
        logger.warning("--execute passed but TOPSTEP_TRADING_ENABLED is not true; only simulated orders will occur")

    if args.once:
        await _once(args.symbol, execute=args.execute)
    else:
        await run_chart_tracker_loop(
            symbol=args.symbol,
            interval_seconds=args.interval,
            execute=args.execute,
            max_iterations=args.max_iterations,
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Chart tracker loop stopped by user")
        sys.exit(0)
