"""
Real-time signal demo for the focus universe using Yahoo Finance data and the
MassiveAnalyst price-action model.  If MASSIVE_API_KEY is set, the script also
queries Massive's previous-close endpoint for the official last close and uses
that as the current price while still using Yahoo for historical candles (the
Massive free tier does not include historical aggregate ranges).

Symbols covered: SPY, QQQ, TSLA, GLD, ES, NQ, GC, XAUUSD
"""
import asyncio
import os
import warnings
from datetime import datetime
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from loguru import logger

logger.remove()
logger.add(lambda msg: None, level="ERROR")

try:
    import yfinance as yf
except ImportError:
    raise SystemExit("yfinance is required: pip install yfinance")

from strategies.fmz_parser import FMZParser
from strategies.fmz_runtime import FMZRuntime, infer_fmz_exchange_name, is_quality_fmz_strategy
from agents.massive_analyst import MassiveAnalyst
from models.decision_schemas import Direction


FOCUS_SYMBOLS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TSLA": "TSLA",
    "GLD": "GLD",
    "ES": "ES=F",
    "NQ": "NQ=F",
    "GC": "GC=F",
    "XAUUSD": "GC=F",  # Yahoo does not list XAUUSD spot; use gold futures proxy
}

QUALITY_FMZ_IDENTIFIERS = [
    "fmz_strategy_4872",
    "fmz_btc_139b",
]

# Massive's previous-close endpoint works cleanly for equities/ETFs on the free tier.
# Futures/forex use different ticker conventions and are handled by Yahoo below.
MASSIVE_EQUITY_SYMBOLS = {"SPY", "QQQ", "TSLA", "GLD"}


def fetch_yahoo_ohlcv(yahoo_ticker: str, period: str = "1mo", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Download OHLCV from Yahoo Finance."""
    try:
        df = yf.download(yahoo_ticker, period=period, interval=interval, progress=False, threads=False)
        if df is None or df.empty:
            return None
        # Flatten multi-index columns if present.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0].lower() for c in df.columns]
        else:
            df.columns = [str(c).lower().replace("adj close", "adj_close") for c in df.columns]
        df = df.dropna()
        return df
    except Exception as e:
        print(f"  Yahoo fetch failed for {yahoo_ticker}: {e}")
        return None


def df_to_candles(df: pd.DataFrame) -> List[Dict]:
    """Convert Yahoo DataFrame to Massive-style candle dicts."""
    candles = []
    for _, row in df.iterrows():
        candles.append({
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": int(row.get("volume", 0)),
        })
    return candles


def massive_style_signal(symbol: str, candles: List[Dict], current_price: Optional[float] = None) -> Optional[Dict]:
    """Run MassiveAnalyst's price-action logic on Yahoo candles."""
    if len(candles) < 2:
        return None
    current = current_price if current_price is not None else candles[-1]["close"]
    direction, confidence, key_points, risks = MassiveAnalyst._evaluate(None, candles, None, current)
    return {
        "symbol": symbol,
        "source": "massive-style (Massive prev-close + Yahoo history)" if current_price is not None else "massive-style (Yahoo)",
        "direction": direction.value if hasattr(direction, "value") else str(direction).lower(),
        "confidence": confidence,
        "current_price": current,
        "key_points": key_points,
        "risks": risks,
    }


def fmz_signals_for_symbol(symbol: str, df: pd.DataFrame) -> List[Dict]:
    """Run quality FMZ strategies on real OHLCV."""
    parser = FMZParser()
    catalog = parser.load_catalog()
    lookup = {e.python_identifier: e for e in catalog}

    signals = []
    for ident in QUALITY_FMZ_IDENTIFIERS:
        entry = lookup.get(ident)
        if not entry or not is_quality_fmz_strategy(entry.source_code, entry.description):
            continue
        args = {a["argument"]: a["default"] for a in entry.arguments}
        runtime = FMZRuntime(
            source_code=entry.source_code,
            language=entry.source_language,
            strategy_name=ident,
            args=args,
        )
        batch = runtime.run(
            symbol=symbol,
            ohlcv_df=df,
            tick_limit=2,
            exchange_name=infer_fmz_exchange_name(symbol),
            max_signals=1,
            quality_only=True,
        )
        for sig in batch:
            signals.append({
                "strategy": ident,
                "direction": sig.direction,
                "entry": round(sig.entry_price, 2),
                "stop": round(sig.stop_price, 2),
                "target": round(sig.target_price, 2),
                "conviction": sig.conviction,
            })
    return signals


async def fetch_massive_prev_closes(symbols: List[str]) -> Dict[str, float]:
    """
    Query Massive's previous-close endpoint for equity symbols.

    The Massive free tier allows previous close but not historical aggregate
    ranges, so we use this as the official current price and keep Yahoo for
    historical candles.  Requests are spaced to respect the 5 req/min limit.
    """
    if not os.getenv("MASSIVE_API_KEY"):
        return {}
    from market_data.providers.massive_provider import MassiveProvider
    config = {"market_data_apis": {"massive": {"enabled": True, "api_key": os.getenv("MASSIVE_API_KEY")}}}
    provider = MassiveProvider(config)
    prices: Dict[str, float] = {}
    candidates = [s for s in symbols if s in MASSIVE_EQUITY_SYMBOLS]
    try:
        for i, sym in enumerate(candidates):
            try:
                data = await provider.get_previous_close(sym)
                result = (data or {}).get("results", [{}])[0]
                close = result.get("c")
                if close is not None:
                    prices[sym] = float(close)
            except Exception as e:
                print(f"  Massive previous-close failed for {sym}: {e}")
            if i < len(candidates) - 1:
                await asyncio.sleep(13)
    finally:
        await provider.close()
    return prices


def main():
    print(f"Real signals for focus universe ({datetime.utcnow().isoformat()}Z)")
    print("=" * 70)

    symbols = list(FOCUS_SYMBOLS.keys())
    massive_prices = asyncio.run(fetch_massive_prev_closes(symbols))
    if massive_prices:
        print(f"Massive previous-close prices fetched for {len(massive_prices)} symbol(s)")

    for symbol, yahoo_ticker in FOCUS_SYMBOLS.items():
        print(f"\n{symbol} (Yahoo: {yahoo_ticker})")
        df = fetch_yahoo_ohlcv(yahoo_ticker)
        if df is None or df.empty:
            print("  No market data available")
            continue

        candles = df_to_candles(df)
        latest = candles[-1]
        yahoo_close = latest["close"]
        massive_close = massive_prices.get(symbol)
        current_price = massive_close if massive_close is not None else yahoo_close
        price_source = "Massive" if massive_close is not None else "Yahoo"
        print(f"  Last close: {current_price:.2f} ({price_source}), volume: {latest['volume']:,}")

        # Massive-style signal from Yahoo candles + official current price
        sig = massive_style_signal(symbol, candles, current_price)
        if sig and sig["direction"] != "neutral":
            print(f"  Massive-style signal: {sig['direction'].upper()} (confidence {sig['confidence']:.2f})")
            for kp in sig["key_points"]:
                print(f"    - {kp}")
        else:
            print(f"  Massive-style signal: NEUTRAL (confidence {sig['confidence']:.2f})")

        # FMZ quality strategy signals
        fmz = fmz_signals_for_symbol(symbol, df)
        if fmz:
            print(f"  FMZ quality signals ({len(fmz)}):")
            for f in fmz:
                print(f"    {f['strategy']}: {f['direction'].upper()} entry={f['entry']}, stop={f['stop']}, target={f['target']}")
        else:
            print("  FMZ quality signals: none")


if __name__ == "__main__":
    main()
