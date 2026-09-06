"""
Focused FMZ strategy smoke test for SPY, QQQ, TSLA, GLD, GC, ES, NQ, XAUUSD.

Runs all real JS/Python FMZ strategies against synthetic OHLCV for each focus
symbol. Each symbol runs in its own process so a hung strategy cannot block the
whole test. Per-strategy timeouts use SIGALRM; strategies that ignore SIGALRM
are killed at the symbol-process level.
"""
import warnings
warnings.filterwarnings("ignore")
import signal
import multiprocessing as mp
import argparse
import time
import pandas as pd
import numpy as np
from loguru import logger

logger.remove()
logger.add(lambda msg: None, level="ERROR")

from strategies.fmz_parser import FMZParser
from strategies.fmz_runtime import FMZRuntime, infer_fmz_exchange_name, is_quality_fmz_strategy


SYMBOLS = {
    "SPY": 450, "QQQ": 380, "TSLA": 250, "GLD": 180,
    "GC": 2000, "ES": 4500, "NQ": 15000, "XAUUSD": 1900,
}


class TimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise TimeoutException("timeout")


def make_ohlcv(base: float, n: int = 50, seed: int = 42):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, base * 0.005, n)
    close = base + np.cumsum(noise)
    return pd.DataFrame({
        "open": close - np.abs(rng.normal(0, base * 0.003, n)),
        "high": close + np.abs(rng.normal(0, base * 0.004, n)),
        "low": close - np.abs(rng.normal(0, base * 0.004, n)),
        "close": close,
        "volume": rng.integers(100000, 1000000, n),
    })


def run_symbol(sym, base, real, timeout_sec, max_signals, symbol_timeout_sec, quality_only):
    """Run all strategies for one symbol. Executed in a separate process."""
    df = make_ohlcv(base)
    exchange_name = infer_fmz_exchange_name(sym)

    signals = 0
    errors = 0
    timeouts = 0
    signal_strategies = []

    start = time.time()
    for entry in real:
        if time.time() - start > symbol_timeout_sec:
            timeouts += len(real) - len(signal_strategies) - errors - timeouts
            break

        if quality_only and not is_quality_fmz_strategy(entry.source_code, entry.description):
            continue

        runtime = FMZRuntime(
            source_code=entry.source_code,
            language=entry.source_language,
            strategy_name=entry.python_identifier,
            timeframe="5m",
        )
        strategy_args = {arg["argument"]: arg["default"] for arg in entry.arguments}
        runtime.args = strategy_args

        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_sec)
        try:
            batch = runtime.run(
                symbol=sym,
                ohlcv_df=df,
                tick_limit=1,
                exchange_name=exchange_name,
                max_signals=max_signals,
                quality_only=quality_only,
            )
            if batch:
                signals += len(batch)
                signal_strategies.append(entry.python_identifier)
        except TimeoutException:
            timeouts += 1
        except KeyboardInterrupt:
            raise
        except BaseException:
            errors += 1
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    return {
        "exchange": exchange_name,
        "signals": signals,
        "errors": errors,
        "timeouts": timeouts,
        "strategies_with_signals": signal_strategies,
    }


def main():
    argparser = argparse.ArgumentParser(description="Focused FMZ smoke test")
    argparser.add_argument("--max-signals", type=int, default=1)
    argparser.add_argument("--timeout", type=int, default=2)
    argparser.add_argument("--symbol-timeout", type=int, default=120)
    argparser.add_argument("--workers", type=int, default=4)
    argparser.add_argument("--symbols", type=str, default=",".join(SYMBOLS.keys()))
    argparser.add_argument("--quality-only", action="store_true", help="Run only indicator/rule-based strategies")
    args = argparser.parse_args()

    mp.set_start_method("spawn", force=True)

    fmz_parser = FMZParser()
    catalog = fmz_parser.build_catalog()
    real = [e for e in catalog if e.parse_status == "ok"]
    if args.quality_only:
        real = [e for e in real if is_quality_fmz_strategy(e.source_code, e.description)]

    selected = [s.strip().upper() for s in args.symbols.split(",")]
    selected = [s for s in selected if s in SYMBOLS]
    if not selected:
        print(f"No valid symbols selected. Valid: {list(SYMBOLS.keys())}")
        return

    tasks = [
        (sym, SYMBOLS[sym], real, args.timeout, args.max_signals, args.symbol_timeout, args.quality_only)
        for sym in selected
    ]

    start = time.time()
    results = {}
    with mp.Pool(processes=args.workers) as pool:
        for sym, result in zip(selected, pool.starmap(run_symbol, tasks)):
            results[sym] = result

    test_label = "FMZ focus-symbol smoke test (quality-only)" if args.quality_only else "FMZ focus-symbol smoke test"
    print(test_label)
    print(f"Catalog: {len(catalog)} markdown files, {len(real)} real JS/Python strategies")
    print(f"max_signals={args.max_signals}, timeout={args.timeout}s, workers={args.workers}, quality_only={args.quality_only}, elapsed={time.time()-start:.1f}s")
    print()
    for sym, r in results.items():
        print(f"{sym} ({r['exchange']}): signals={r['signals']}, errors={r['errors']}, timeouts={r['timeouts']}")
        if r["strategies_with_signals"]:
            print(f"  strategies with signals ({len(r['strategies_with_signals'])}):")
            for name in r["strategies_with_signals"][:20]:
                print(f"    {name}")


if __name__ == "__main__":
    main()
