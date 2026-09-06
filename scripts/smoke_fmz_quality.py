"""Smoke-test only the indicator-based FMZ strategies for the focus universe."""
import warnings
warnings.filterwarnings("ignore")
import signal
import multiprocessing as mp
import argparse
import time
import re
import traceback
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


def is_quality(entry):
    return is_quality_fmz_strategy(entry.source_code, entry.description)


def run_symbol(sym, base, quality, timeout_sec, max_signals, symbol_timeout_sec):
    df = make_ohlcv(base)
    exchange_name = infer_fmz_exchange_name(sym)

    signals = 0
    errors = 0
    timeouts = 0
    signal_strategies = []
    error_samples = {}
    timeout_strategies = []

    start = time.time()
    for entry in quality:
        if time.time() - start > symbol_timeout_sec:
            remaining = len(quality) - len(signal_strategies) - errors - timeouts
            timeouts += remaining
            break

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
            )
            if batch:
                signals += len(batch)
                signal_strategies.append(entry.python_identifier)
        except TimeoutException:
            timeouts += 1
            timeout_strategies.append(entry.python_identifier)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            errors += 1
            key = f"{type(e).__name__}: {str(e)[:80]}"
            error_samples.setdefault(key, []).append(entry.python_identifier)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)

    return {
        "exchange": exchange_name,
        "signals": signals,
        "errors": errors,
        "timeouts": timeouts,
        "strategies_with_signals": signal_strategies,
        "error_samples": error_samples,
        "timeout_strategies": timeout_strategies,
    }


def main():
    argparser = argparse.ArgumentParser(description="FMZ quality-only smoke test")
    argparser.add_argument("--max-signals", type=int, default=1)
    argparser.add_argument("--timeout", type=int, default=2)
    argparser.add_argument("--symbol-timeout", type=int, default=120)
    argparser.add_argument("--workers", type=int, default=4)
    argparser.add_argument("--symbols", type=str, default=",".join(SYMBOLS.keys()))
    args = argparser.parse_args()

    mp.set_start_method("spawn", force=True)

    fmz_parser = FMZParser()
    catalog = fmz_parser.build_catalog()
    real = [e for e in catalog if e.parse_status == "ok"]
    quality = [e for e in real if is_quality(e)]

    selected = [s.strip().upper() for s in args.symbols.split(",")]
    selected = [s for s in selected if s in SYMBOLS]

    tasks = [
        (sym, SYMBOLS[sym], quality, args.timeout, args.max_signals, args.symbol_timeout)
        for sym in selected
    ]

    start = time.time()
    results = {}
    with mp.Pool(processes=args.workers) as pool:
        for sym, result in zip(selected, pool.starmap(run_symbol, tasks)):
            results[sym] = result

    print("FMZ quality-only smoke test")
    print(f"Catalog: {len(catalog)} markdown, {len(real)} real, {len(quality)} indicator-based")
    print(f"max_signals={args.max_signals}, timeout={args.timeout}s, workers={args.workers}, elapsed={time.time()-start:.1f}s")
    print()
    for sym, r in results.items():
        print(f"{sym} ({r['exchange']}): signals={r['signals']}, errors={r['errors']}, timeouts={r['timeouts']}")
        if r["strategies_with_signals"]:
            print(f"  signal strategies ({len(r['strategies_with_signals'])}):")
            for name in r["strategies_with_signals"][:20]:
                print(f"    {name}")
        if r["timeout_strategies"]:
            print(f"  timeout strategies ({len(r['timeout_strategies'])}):")
            for name in r["timeout_strategies"][:10]:
                print(f"    {name}")
        if r["error_samples"]:
            print(f"  top error samples:")
            for key, names in sorted(r["error_samples"].items(), key=lambda x: -len(x[1]))[:5]:
                print(f"    {len(names)}x {key}")
                for n in names[:3]:
                    print(f"      {n}")


if __name__ == "__main__":
    main()
