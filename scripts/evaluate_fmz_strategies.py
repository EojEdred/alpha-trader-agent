#!/usr/bin/env python3
"""
Evaluate all quality FMZ strategies on the focus universe.

For each strategy, runs it on each symbol over the requested lookback and
reports aggregate win rate, profit factor, and P&L.  Uses the same simulation
engine as backtest_focus.py so results are comparable.

Usage:
    source venv/bin/activate
    python scripts/evaluate_fmz_strategies.py --days 90 --account-value 100000
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import pandas as pd

_REPO_ROOT = "/Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent"
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.backtest_focus import simulate_trade
from scripts.live_intents import (
    FOCUS_SYMBOLS,
    DEFAULT_VENUE_MAP,
    build_fmz_intent,
    fetch_yahoo_ohlcv,
    size_intent,
)
from strategies.fmz_parser import FMZParser
from strategies.fmz_runtime import FMZRuntime, infer_fmz_exchange_name, is_quality_fmz_strategy
from tools.risk_governor import RiskGovernor


async def evaluate_strategy(
    ident: str,
    entry: Any,
    days: int,
    account_value: float,
) -> Dict[str, Any]:
    config = {
        "portfolio": {"max_risk_per_trade_pct": 0.5, "max_loss_per_day_pct": 2.0},
        "risk_limits": {"min_risk_reward": 2.0, "max_position_pct": 5.0},
    }
    governor = RiskGovernor(config)
    params: Dict[str, Any] = {}

    all_results: List[Dict[str, Any]] = []

    args = {a["argument"]: a["default"] for a in entry.arguments}

    for symbol, yahoo_ticker in FOCUS_SYMBOLS.items():
        df = fetch_yahoo_ohlcv(yahoo_ticker, period="1y", interval="1d")
        if df is None or df.empty or len(df) < days + 5:
            continue

        venue = DEFAULT_VENUE_MAP.get(symbol, "backtest")
        max_hold_days = 5

        for i in range(-days, 0):
            train_df = df.iloc[:i]
            future_df = df.iloc[i : i + max_hold_days]
            if future_df.empty or len(train_df) < 30:
                continue

            runtime = FMZRuntime(
                source_code=entry.source_code,
                language=entry.source_language,
                strategy_name=ident,
                args=args,
            )
            batch = runtime.run(
                symbol=symbol,
                ohlcv_df=train_df,
                tick_limit=2,
                exchange_name=infer_fmz_exchange_name(symbol),
                max_signals=1,
                quality_only=True,
            )
            for sig in batch:
                intent = build_fmz_intent(symbol, {
                    "strategy": ident,
                    "direction": sig.direction,
                    "entry": round(sig.entry_price, 2),
                    "stop": round(sig.stop_price, 2),
                    "target": round(sig.target_price, 2),
                    "conviction": sig.conviction,
                }, venue)
                size_intent(intent, account_value, config, params)
                decision = await governor.validate(intent, {"account_value": account_value})
                if not decision.approved:
                    continue

                pnl, bars_held = simulate_trade(intent, future_df, max_hold_days)
                all_results.append({
                    "date": str(future_df.index[0])[:10],
                    "symbol": symbol,
                    "direction": intent.direction,
                    "entry": intent.entry_price,
                    "exit": intent.entry_price + (pnl / intent.size) if intent.size else intent.entry_price,
                    "bars_held": bars_held,
                    "size": intent.size,
                    "pnl": pnl,
                })

    if not all_results:
        return {"ident": ident, "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "pf": 0.0, "pnl": 0.0}

    wins = sum(1 for r in all_results if r["pnl"] > 0)
    losses = sum(1 for r in all_results if r["pnl"] < 0)
    total = len(all_results)
    win_rate = wins / total * 100 if total else 0.0
    total_pnl = sum(r["pnl"] for r in all_results)

    avg_win = sum(r["pnl"] for r in all_results if r["pnl"] > 0) / max(wins, 1)
    avg_loss = sum(r["pnl"] for r in all_results if r["pnl"] < 0) / max(losses, 1)
    pf = abs(avg_win * wins / (avg_loss * losses)) if losses else float("inf")

    return {
        "ident": ident,
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "pf": pf,
        "pnl": total_pnl,
    }


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--account-value", type=float, default=100000.0)
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum trades to be ranked")
    args = parser.parse_args()

    parser = FMZParser()
    catalog = parser.load_catalog()
    quality = [e for e in catalog if is_quality_fmz_strategy(e.source_code, e.description)]

    print(f"Evaluating {len(quality)} quality FMZ strategies over last {args.days} days")
    print("=" * 80)

    results = []
    for entry in quality:
        ident = entry.python_identifier
        print(f"\nRunning {ident}...")
        result = await evaluate_strategy(ident, entry, args.days, args.account_value)
        results.append(result)
        print(
            f"  trades={result['trades']}  wins={result['wins']}  losses={result['losses']}  "
            f"WR={result['win_rate']:.1f}%  PF={result['pf']:.2f}  P&L=${result['pnl']:,.2f}"
        )

    print("\n" + "=" * 80)
    print("Ranked by P&L (min {} trades)".format(args.min_trades))
    print("-" * 80)
    ranked = sorted(
        [r for r in results if r["trades"] >= args.min_trades],
        key=lambda x: x["pnl"],
        reverse=True,
    )
    for r in ranked:
        print(
            f"{r['ident']:<45} T={r['trades']:>3}  W={r['wins']:>3}  L={r['losses']:>3}  "
            f"WR={r['win_rate']:>5.1f}%  PF={r['pf']:>5.2f}  P&L=${r['pnl']:>10,.2f}"
        )

    if not ranked:
        print("No strategies met the minimum-trade threshold.")


if __name__ == "__main__":
    asyncio.run(main())
