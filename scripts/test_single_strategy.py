"""Run a single FMZ strategy and print any error with traceback."""
import warnings
warnings.filterwarnings("ignore")
import sys
import pandas as pd
import numpy as np
from strategies.fmz_parser import FMZParser
from strategies.fmz_runtime import FMZRuntime, infer_fmz_exchange_name


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


if __name__ == "__main__":
    name = sys.argv[1]
    sym = sys.argv[2] if len(sys.argv) > 2 else "SPY"
    parser = FMZParser()
    catalog = parser.build_catalog()
    e = next(x for x in catalog if x.python_identifier == name)
    runtime = FMZRuntime(e.source_code, e.source_language, strategy_name=name)
    args = {arg["argument"]: arg["default"] for arg in e.arguments}
    runtime.args = args
    df = make_ohlcv({"SPY": 450, "QQQ": 380, "TSLA": 250, "GLD": 180, "GC": 2000, "ES": 4500, "NQ": 15000, "XAUUSD": 1900}[sym])
    try:
        batch = runtime.run(symbol=sym, ohlcv_df=df, tick_limit=5, exchange_name=infer_fmz_exchange_name(sym), max_signals=1)
        print("signals:", len(batch))
        for s in batch:
            print(s)
    except Exception as ex:
        import traceback
        traceback.print_exc()
