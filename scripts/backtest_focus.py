#!/usr/bin/env python3
"""
2-week walk-forward backtest for the focus universe using BOTH
Massive-style and FMZ quality signals.

For each trading day in the lookback window, the script uses data up to the
previous close to generate the same signals that live_intents.py would
generate, deduplicates to the best intent per symbol, then simulates entering
at the next open and exiting at the next close.  This validates the full
signal pipeline against actual market prints.

Usage:
    python scripts/backtest_focus.py --days 14 --account-value 100000
"""

import argparse
import asyncio
import json
import os
import sys
import warnings
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from loguru import logger

warnings.filterwarnings("ignore")

# Ensure the repo root is importable regardless of cwd.
_REPO_ROOT = "/Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent"
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.live_intents import (
    FOCUS_SYMBOLS,
    DEFAULT_VENUE_MAP,
    deduplicate_intents,
    df_to_candles,
    fetch_yahoo_ohlcv,
    fmz_signals_for_symbol,
    massive_style_signal,
    mean_reversion_signal,
    pullback_trend_signal,
    breakout_signal,
    size_intent,
    build_massive_intent,
    build_fmz_intent,
    build_mean_reversion_intent,
    build_pullback_trend_intent,
    build_breakout_intent,
    trend_aligned,
    confirmed_intents,
    spy_regime_aligned,
    volatility_not_extreme,
    strong_trend_aligned,
    fetch_hourly_ohlcv,
    hourly_trend_aligned,
    momentum_aligned,
    fetch_vix_daily,
    vix_info_for_date,
    vix_allows_long,
    rank_select_top_n,
    source_symbol_allowed,
)
from tools.risk_governor import RiskGovernor

logger.remove()
logger.add(sys.stderr, level="WARNING")


def simulate_trade(intent, future_df, max_hold_days: int = 5) -> tuple[float, int]:
    """
    Simulate holding a trade up to max_hold_days.

    Exit at stop/target if daily range touches it; otherwise exit at the close
    of the final day. Returns (pnl, bars_held).  Uses the intent's contract
    multiplier so futures P&L is realistic.
    """
    entry = intent.entry_price
    stop = intent.stop_price
    target = intent.target_price
    size = intent.size
    multiplier = getattr(intent, "contract_multiplier", 1.0) or 1.0
    days_held = 0

    for idx in range(min(max_hold_days, len(future_df))):
        row = future_df.iloc[idx]
        high = float(row.get("high"))
        low = float(row.get("low"))
        days_held += 1

        if intent.direction == "long":
            if low <= stop:
                return (stop - entry) * size * multiplier, days_held
            if high >= target:
                return (target - entry) * size * multiplier, days_held
        else:  # short
            if high >= stop:
                return (entry - stop) * size * multiplier, days_held
            if low <= target:
                return (entry - target) * size * multiplier, days_held

    # No stop/target hit — exit at final close.
    close = float(future_df.iloc[days_held - 1].get("close"))
    if intent.direction == "long":
        return (close - entry) * size * multiplier, days_held
    return (entry - close) * size * multiplier, days_held


async def run_backtest(days: int, account_value: float, top_n: int = 2, symbols: Optional[List[str]] = None) -> None:
    symbols = symbols or list(FOCUS_SYMBOLS.keys())
    print(f"\nFocus universe backtest — last {days} trading days")
    print(f"Symbols: {', '.join(symbols)}")
    print("Includes Massive-style + FMZ quality signals, deduplicated per symbol")
    print("=" * 70)

    config = {
        "portfolio": {"max_risk_per_trade_pct": 0.5, "max_loss_per_day_pct": 2.0},
        "risk_limits": {"min_risk_reward": 2.0, "max_position_pct": 5.0},
    }
    params: Dict[str, Any] = {}
    governor = RiskGovernor(config)

    # Load SPY once for the broad equity-index regime filter.
    spy_df = fetch_yahoo_ohlcv("SPY", period="1y", interval="1d")
    if spy_df is None or spy_df.empty:
        print("Warning: SPY data unavailable; equity-index regime filter disabled")
        spy_df = None

    # Load VIX history for fear-gauge confirmation on long trades.
    vix_df = fetch_vix_daily(period="1y")
    if vix_df is None or vix_df.empty:
        print("Warning: VIX data unavailable; VIX guard disabled")
        vix_df = None

    all_candidates: List[Tuple[str, str, pd.DataFrame, TradeIntent]] = []

    for symbol in symbols:
        yahoo_ticker = FOCUS_SYMBOLS[symbol]
        print(f"\n{symbol} ({yahoo_ticker})")
        venue = DEFAULT_VENUE_MAP.get(symbol, "backtest")
        df = fetch_yahoo_ohlcv(yahoo_ticker, period="1y", interval="1d")
        if df is None or df.empty or len(df) < days + 5:
            print("  Insufficient data")
            continue

        # Load hourly chart for multi-timeframe confirmation in the backtest.
        hourly_df = fetch_hourly_ohlcv(yahoo_ticker)

        max_hold_days = 5
        for i in range(-days, 0):
            train_df = df.iloc[:i]
            future_df = df.iloc[i : i + max_hold_days]
            if future_df.empty:
                continue

            candles = df_to_candles(train_df)
            current_price = candles[-1]["close"] if candles else None

            # SPY regime, VIX, and hourly alignment use data up to the same calendar date.
            target_date = train_df.index[-1] if len(train_df) > 0 else None
            spy_train_df = None
            if spy_df is not None and target_date is not None:
                spy_train_df = spy_df[spy_df.index <= target_date]
                if spy_train_df.empty:
                    spy_train_df = None
            vix_info = vix_info_for_date(vix_df, target_date) if vix_df is not None and target_date is not None else None

            mass_intents = []
            fmz_intents = []

            # Massive-style signal
            mass_sig = massive_style_signal(symbol, candles, current_price)
            if mass_sig and mass_sig["direction"] != "neutral":
                if trend_aligned(train_df, mass_sig["direction"]) and source_symbol_allowed("massive_style", symbol, params):
                    intent = build_massive_intent(symbol, mass_sig, train_df, venue, params)
                    if intent:
                        mass_intents.append(intent)

            # FMZ quality signals
            fmz_sigs = fmz_signals_for_symbol(symbol, train_df)
            for sig in fmz_sigs:
                if not trend_aligned(train_df, sig["direction"]):
                    continue
                if not source_symbol_allowed(sig["strategy"], symbol, params):
                    continue
                fmz_intents.append(build_fmz_intent(symbol, sig, venue))

            # Mean-reversion signal: buy/sell stretched price back to the Bollinger mean.
            mr_intents = []
            mr_sig = mean_reversion_signal(symbol, train_df, current_price, hourly_df, vix_info, target_date)
            if mr_sig and strong_trend_aligned(train_df, mr_sig["direction"]) and source_symbol_allowed("mean_reversion", symbol, params):
                intent = build_mean_reversion_intent(symbol, mr_sig, train_df, venue, params)
                if intent:
                    mr_intents.append(intent)

            # Pullback-to-trend signal for indices and high-beta equities.
            pb_intents = []
            pb_sig = pullback_trend_signal(symbol, train_df, current_price)
            if pb_sig and source_symbol_allowed("pullback_trend", symbol, params):
                intent = build_pullback_trend_intent(symbol, pb_sig, train_df, venue, params)
                if intent:
                    pb_intents.append(intent)

            # Breakout signal: quiet consolidation breakout in direction of regime.
            bo_intents = []
            bo_sig = breakout_signal(symbol, train_df, current_price)
            if bo_sig and source_symbol_allowed("breakout", symbol, params):
                intent = build_breakout_intent(symbol, bo_sig, train_df, venue, params)
                if intent:
                    bo_intents.append(intent)

            daily_intents = confirmed_intents(mass_intents, fmz_intents) + mr_intents + pb_intents + bo_intents
            if not daily_intents:
                continue

            filtered = []
            for intent in daily_intents:
                is_pullback = intent.thesis_id == "pullback_trend"
                if symbol in ("SPY", "QQQ", "ES", "NQ") and not is_pullback and not strong_trend_aligned(train_df, intent.direction):
                    continue
                if intent.thesis_id != "mean_reversion" and not spy_regime_aligned(symbol, intent.direction, spy_train_df):
                    continue
                if not hourly_trend_aligned(hourly_df, intent.direction, target_date=target_date):
                    continue
                if not momentum_aligned(train_df, intent.direction):
                    continue
                if intent.direction == "long" and not vix_allows_long(vix_info):
                    continue
                extreme_vol_threshold = 0.95 if is_pullback else 0.80
                if not volatility_not_extreme(train_df, low_pct=0.10, high_pct=extreme_vol_threshold):
                    continue
                filtered.append(intent)

            if not filtered:
                continue

            daily_intents = deduplicate_intents(filtered)

            trade_date = str(future_df.index[0])[:10]
            for intent in daily_intents:
                # Stamp the intent with its decision date so daily ranking works.
                intent.created_at = target_date.to_pydatetime()
                all_candidates.append((symbol, trade_date, future_df, intent))

    if not all_candidates:
        print("\nNo candidate intents generated.")
        return

    # Rank across all symbols and keep only the top-N setups per calendar day.
    ranked_intents = rank_select_top_n(
        [intent for _, _, _, intent in all_candidates], top_n=top_n
    )
    ranked_ids = {intent.id for intent in ranked_intents}
    print(f"\n{len(ranked_intents)} top-ranked intents selected from {len(all_candidates)} candidates")

    candidate_lookup = {intent.id: (symbol, trade_date, future_df) for symbol, trade_date, future_df, intent in all_candidates}

    all_results: List[Dict[str, Any]] = []
    symbol_stats: Dict[str, Dict[str, Any]] = {}

    for intent in ranked_intents:
        symbol, trade_date, future_df = candidate_lookup[intent.id]
        size_intent(intent, account_value, config, params)
        decision = await governor.validate(
            intent, {"account_value": account_value}
        )
        if not decision.approved:
            continue

        pnl, bars_held = simulate_trade(intent, future_df, max_hold_days)
        stats = symbol_stats.setdefault(symbol, {"pnl": 0.0, "wins": 0, "losses": 0})
        stats["pnl"] += pnl
        if pnl > 0:
            stats["wins"] += 1
        elif pnl < 0:
            stats["losses"] += 1

        exit_price = (
            intent.entry_price + (pnl / intent.size)
            if intent.size
            else intent.entry_price
        )
        all_results.append(
            {
                "date": trade_date,
                "symbol": symbol,
                "direction": intent.direction,
                "source": intent.thesis_id,
                "entry": round(intent.entry_price, 2),
                "exit": round(exit_price, 2),
                "bars_held": bars_held,
                "size": intent.size,
                "pnl": round(pnl, 2),
            }
        )

    print("\nPer-symbol results")
    print("-" * 70)
    for symbol, stats in sorted(symbol_stats.items()):
        wins = stats["wins"]
        losses = stats["losses"]
        print(
            f"  {symbol:6} P&L: ${stats['pnl']:>10,.2f} | Wins: {wins} | Losses: {losses} | "
            f"Trades: {wins + losses}"
        )

    if not all_results:
        print("\nNo trades generated.")
        return

    total_pnl = sum(r["pnl"] for r in all_results)
    wins = sum(1 for r in all_results if r["pnl"] > 0)
    losses = sum(1 for r in all_results if r["pnl"] < 0)
    avg_win = sum(r["pnl"] for r in all_results if r["pnl"] > 0) / max(wins, 1)
    avg_loss = sum(r["pnl"] for r in all_results if r["pnl"] < 0) / max(losses, 1)
    pf = abs(avg_win * wins / (avg_loss * losses)) if losses else float("inf")

    print("\n" + "=" * 70)
    print("Aggregate results")
    print("-" * 70)
    print(f"Total P&L:        ${total_pnl:,.2f}")
    print(f"Total trades:     {len(all_results)}")
    print(f"Wins:             {wins}")
    print(f"Losses:           {losses}")
    print(f"Win rate:         {wins / max(len(all_results), 1) * 100:.1f}%")
    print(f"Avg win:          ${avg_win:,.2f}")
    print(f"Avg loss:         ${avg_loss:,.2f}")
    print(f"Profit factor:    {pf:.2f}")
    print("-" * 70)
    print("Results by signal source")
    print("-" * 70)
    source_stats = defaultdict(lambda: {"pnl": 0.0, "wins": 0, "losses": 0, "trades": 0})
    for r in all_results:
        src = r["source"]
        source_stats[src]["pnl"] += r["pnl"]
        source_stats[src]["trades"] += 1
        if r["pnl"] > 0:
            source_stats[src]["wins"] += 1
        elif r["pnl"] < 0:
            source_stats[src]["losses"] += 1
    for src, s in sorted(source_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        print(
            f"  {src:20} P&L=${s['pnl']:>10.2f}  "
            f"W:{s['wins']} L:{s['losses']} T:{s['trades']}"
        )
    print("=" * 70)
    result_path = os.path.join(_REPO_ROOT, "data", "backtest_focus_result.json")
    trades_path = os.path.join(_REPO_ROOT, "data", "backtest_focus_trades.json")
    result = {
        "ran_at": datetime.utcnow().isoformat(),
        "days": days,
        "account_value": account_value,
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(all_results),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / max(len(all_results), 1) * 100, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(pf, 2),
        "go_live_ready": pf >= 1.2,
    }
    try:
        os.makedirs(os.path.dirname(result_path), exist_ok=True)
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)
        with open(trades_path, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"Result saved to {result_path}")
        print(f"Trades saved to {trades_path}")
    except Exception as e:
        logger.warning(f"Could not save backtest result: {e}")

    if pf >= 1.2:
        print("✅ Profit factor >= 1.2 — passes rough go-live threshold")
    else:
        print("❌ Profit factor < 1.2 — NOT ready for live capital")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--account-value", type=float, default=100000.0)
    parser.add_argument("--top-n", type=int, default=3, help="Top-N intents per calendar day")
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Limit backtest to these focus symbols (e.g. SPY QQQ)",
    )
    args = parser.parse_args()
    symbols = args.symbols or list(FOCUS_SYMBOLS.keys())
    asyncio.run(run_backtest(args.days, args.account_value, args.top_n, symbols))
