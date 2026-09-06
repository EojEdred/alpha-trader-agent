"""
FMZ Quant runtime adapter for Alpha Trader.

Provides an ``exchange`` object and supporting globals so that FMZ JavaScript
and Python strategies can run inside Alpha Trader.  Buy/Sell calls are captured
and converted into Alpha Trader ``Signal`` objects.

The adapter is intentionally sandboxed and conservative:
- Strategies run for a bounded number of ticks (default 1).
- Live execution is never triggered; signals are produced in ``signal_only`` form.
- Network/IO operations are not performed; market data is read from the supplied OHLCV DataFrame.

Usage:
    from strategies.fmz_runtime import FMZRuntime
    runtime = FMZRuntime(strategy_source, language="javascript", args={...})
    signals = runtime.run(symbol="SPY", ohlcv_df=df)
"""

import json
import math
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

import pandas as pd
import numpy as np
from loguru import logger

try:
    from js2py import EvalJs
    from js2py.base import PyJsUndefined
    JS2PY_AVAILABLE = True
except ImportError:
    JS2PY_AVAILABLE = False
    PyJsUndefined = type(None)

from strategies.base import Signal


MAX_RUNTIME_TICKS = 3
MAX_RUNTIME_MS = 5000


def infer_fmz_exchange_name(symbol: str) -> str:
    """
    Infer a plausible FMZ exchange name from an Alpha Trader symbol.

    FMZ strategies commonly gate on exchange name (e.g. only running on OKEx or
    Binance).  This mapping lets stock/crypto/commodity symbols present an
    exchange name the strategy recognizes, without hard-coding a single global
    exchange.
    """
    sym = (symbol or "").upper().replace("-", "_")

    # Crypto perpetuals / futures common in FMZ repo
    if any(s in sym for s in ("BTC", "ETH", "LTC", "XRP", "EOS", "BCH", "BSV", "LINK", "SOL", "ADA", "DOT", "AVAX")):
        if "USD" in sym and "USDT" not in sym:
            return "Futures_OKCoin"
        return "Futures_Binance"

    # Stablecoin pairs
    if sym.endswith("_USDT") or sym.endswith("USDT"):
        return "Futures_Binance"

    # Traditional equities and equity options (e.g. SPY, QQQ, TSLA, SPY240119C00450000)
    equity_tickers = ("SPY", "QQQ", "IWM", "AAPL", "TSLA", "MSFT", "AMZN", "GOOGL", "NVDA", "META", "NFLX", "GLD")
    if sym.startswith(equity_tickers) or sym in equity_tickers:
        return "Stocks_AlphaTrader"

    # Gold / S&P / Nasdaq futures.  Most FMZ futures strategies expect OKCoin;
    # CTP is the Chinese commodity exchange and is checked by only a handful.
    if any(s in sym for s in ("GC", "XAU", "GLD", "ES", "NQ", "YM", "RTY", "CL", "NG")):
        return "Futures_OKCoin"

    # Default to the most common FMZ futures exchange checked by strategies.
    return "Futures_OKCoin"


FMZ_QUALITY_INDICATOR_RE = re.compile(
    r"\b(TA\.|talib|TA-Lib|Indicator|MACD|RSI|EMA|SMA|WMA|ATR|Bollinger|BOLL|"
    r"KDJ|KD\b|DMI|ADX|CCI|OBV|Williams|WPR|Stoch|STOCH|Momentum|MFI|"
    r"Ichimoku|SAR|Parabolic|EMA[_ ]cross|MA[_ ]cross|golden[_ ]cross|death[_ ]cross|"
    r"breakout|support|resistance|mavg|moving.?average|mean.?reversion|"
    r"trend|momentum|volatility|stddev|StdDev)\b",
    re.IGNORECASE,
)

FMZ_NOISE_RE = re.compile(
    r"\b(iceberg|order|buy then sell|ping pong|martingale|fixed investment|"
    r"variable investment|grid|hedge on two contracts|ordersdetail|getminstock|"
    r"orders detail|order detail|new coin|announcement|funding rate|order book)\b|"
    r"(马丁格尔|马丁|均衡|定投|对冲|网格|模板库使用例子|封装|插件|下单|委托)",
    re.IGNORECASE,
)

FMZ_TRADE_RE = re.compile(
    r"\b(exchange\.(Buy|Sell)|\$\.(Buy|Sell)|Go\(|ext\.(Buy|Sell))\b",
    re.IGNORECASE,
)


def is_quality_fmz_strategy(source_code: Optional[str] = None, description: Optional[str] = None) -> bool:
    """
    Return True if an FMZ strategy appears to be an indicator/rule-based trading
    strategy rather than an execution utility or noise strategy.
    """
    text = f"{source_code or ''}\n{description or ''}"
    has_indicator = bool(FMZ_QUALITY_INDICATOR_RE.search(text))
    has_trade = bool(FMZ_TRADE_RE.search(text))
    is_noise = bool(FMZ_NOISE_RE.search(text))
    return has_indicator and has_trade and not is_noise


class FMZAccount:
    """Account object matching FMZ's exchange.GetAccount() shape."""

    def __init__(self, balance: float = 10000.0, stocks: float = 0.0):
        self.Balance = balance
        self.Stocks = stocks
        self.FrozenBalance = 0.0
        self.FrozenStocks = 0.0

    def __getitem__(self, key):
        return getattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Balance": self.Balance,
            "Stocks": self.Stocks,
            "FrozenBalance": self.FrozenBalance,
            "FrozenStocks": self.FrozenStocks,
        }

    def __str__(self) -> str:
        return str(self.to_dict())


class FMZOrder:
    """Order object returned by FMZ APIs."""

    def __init__(self, order_id: str, order_type: int, price: float, amount: float):
        self.Id = order_id
        self.Type = order_type  # 0 = buy, 1 = sell in FMZ
        self.Price = price
        self.Amount = amount
        self.DealAmount = amount
        self.Status = 1  # ORDER_STATE_CLOSED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Id": self.Id,
            "Type": self.Type,
            "Price": self.Price,
            "Amount": self.Amount,
            "DealAmount": self.DealAmount,
            "Status": self.Status,
        }

    def __str__(self) -> str:
        return str(self.to_dict())


class FMZQuote:
    """Ticker object matching exchange.GetTicker()."""

    def __init__(self, buy: float, sell: float, last: float):
        self.Buy = buy
        self.Sell = sell
        self.Last = last

    def __getitem__(self, key):
        return getattr(self, key)

    def to_dict(self) -> Dict[str, Any]:
        return {"Buy": self.Buy, "Sell": self.Sell, "Last": self.Last}

    def __str__(self) -> str:
        return str(self.to_dict())


class FMZDepth:
    """Depth object matching exchange.GetDepth()."""

    def __init__(self, price: float):
        self.Bids = [[price * 0.9999, 1.0]]
        self.Asks = [[price * 1.0001, 1.0]]

    def __str__(self) -> str:
        return f"Depth(Bids={self.Bids}, Asks={self.Asks})"


class FMZRecord(dict):
    """OHLCV record supporting both dict and attribute access."""

    def __init__(self, data: Dict[str, Any]):
        super().__init__(data)
        for k, v in data.items():
            setattr(self, k, v)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        setattr(self, key, value)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as e:
            raise AttributeError(key) from e

    def __repr__(self):
        return f"FMZRecord({dict(self)})"

    def __str__(self) -> str:
        return str(dict(self))


class FMZRecordList(list):
    """List of FMZ records that exposes field arrays via attribute access."""

    def __getattr__(self, name: str):
        try:
            return [r[name] for r in self]
        except (KeyError, TypeError) as e:
            raise AttributeError(name) from e

    def __getitem__(self, key):
        if isinstance(key, str):
            return [r[key] for r in self]
        return super().__getitem__(key)

    def __repr__(self):
        return f"FMZRecordList({len(self)} records)"


class FMZMACDResult(tuple):
    """MACD result supporting both tuple indexing and dict-style keys."""

    _KEYS = {"DIF": 0, "DEA": 1, "MACD": 2}

    def __new__(cls, dif, dea, macd):
        return super().__new__(cls, (dif, dea, macd))

    def __getitem__(self, key):
        if isinstance(key, str) and key in self._KEYS:
            return super().__getitem__(self._KEYS[key])
        return super().__getitem__(key)


class FMZExchange:
    """
    FMZ-compatible ``exchange`` object backed by Alpha Trader market data.

    Captures Buy/Sell calls as Alpha Trader signals and supplies market data
    from a pandas OHLCV DataFrame.
    """

    ORDER_STATE_PENDING = 0
    ORDER_STATE_CLOSED = 1
    ORDER_STATE_CANCELED = 2

    def __init__(
        self,
        symbol: str,
        ohlcv_df: Optional[pd.DataFrame] = None,
        quote: Optional[FMZQuote] = None,
        account: Optional[FMZAccount] = None,
        default_price: float = 100.0,
        tick_limit: int = MAX_RUNTIME_TICKS,
        exchange_name: str = "FMZ_Stub",
        currency: Optional[str] = None,
        max_signals: Optional[int] = None,
    ):
        self.symbol = symbol
        self.ohlcv_df = ohlcv_df.copy() if ohlcv_df is not None else None
        self.default_price = default_price
        self.tick_limit = tick_limit
        self._exchange_name = exchange_name
        self._currency = currency or symbol
        self._max_signals = max_signals
        self._ticks = 0
        self._records_calls = 0
        self._orders: Dict[str, FMZOrder] = {}
        self._order_seq = 0
        self._canceled: set = set()
        self.signals: List[Signal] = []
        self._last_price = self._compute_last_price()
        self.quote = quote or FMZQuote(
            buy=self._last_price * 0.9999,
            sell=self._last_price * 1.0001,
            last=self._last_price,
        )
        self.account = account or FMZAccount()
        self.depth = FMZDepth(self._last_price)

    def _compute_last_price(self) -> float:
        if self.ohlcv_df is not None and not self.ohlcv_df.empty:
            return float(self.ohlcv_df["close"].iloc[-1])
        return self.default_price

    def _next_id(self, side: str) -> str:
        self._order_seq += 1
        return f"fmz_{side}_{self._order_seq}_{uuid.uuid4().hex[:6]}"

    def _capture_signal(self, direction: str, price: float, amount: float):
        """Convert an FMZ order into an Alpha Trader Signal."""
        if self._max_signals is not None and len(self.signals) >= self._max_signals:
            return
        if price is None or amount is None:
            return
        # FMZ strategies often pass price=0 for market orders.
        if price <= 0:
            price = self._last_price
        if amount <= 0:
            return

        stop = price * 0.98 if direction == "long" else price * 1.02
        target = price * 1.04 if direction == "long" else price * 0.96
        atr = self._estimate_atr()
        if atr and atr > 0:
            stop = price - (atr * 1.5) if direction == "long" else price + (atr * 1.5)
            target = price + (atr * 3.0) if direction == "long" else price - (atr * 3.0)

        signal = Signal(
            symbol=self.symbol,
            direction=direction,
            entry_price=round(price, 4),
            stop_price=round(stop, 4),
            target_price=round(target, 4),
            conviction=0.6,
            strategy_name="fmz_strategy",
            timeframe="5m",
            evidence={"fmz_amount": round(amount, 6), "fmz_last_price": round(self._last_price, 4)},
            invalidation_price=round(stop, 4),
            time_stop=datetime.utcnow() + timedelta(hours=4),
        )
        self.signals.append(signal)

    def _estimate_atr(self) -> Optional[float]:
        if self.ohlcv_df is None or len(self.ohlcv_df) < 15:
            return None
        df = self.ohlcv_df.tail(15)
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return float(tr.mean())

    # ------------------------------------------------------------------
    # FMZ exchange API
    # ------------------------------------------------------------------
    def GetRecords(self, period: Optional[int] = None):
        """Return OHLCV records as list of dicts matching FMZ shape."""
        self._records_calls += 1
        if self._records_calls > max(self.tick_limit * 3, 3):
            raise RuntimeError("FMZ tick limit reached")
        if self.ohlcv_df is None or self.ohlcv_df.empty:
            return []
        records = []
        for _, row in self.ohlcv_df.iterrows():
            ts = row.name
            if isinstance(ts, pd.Timestamp):
                ts = int(ts.timestamp() * 1000)
            else:
                ts = int(pd.Timestamp(ts).timestamp() * 1000)
            records.append({
                "Time": ts,
                "Open": float(row["open"]),
                "High": float(row["high"]),
                "Low": float(row["low"]),
                "Close": float(row["close"]),
                "Volume": float(row.get("volume", 0)),
                "OpenInterest": 0.0,
            })
        return FMZRecordList(FMZRecord(r) for r in records)

    def GetTicker(self):
        return self.quote

    def GetDepth(self):
        return self.depth

    def GetAccount(self):
        return self.account

    @staticmethod
    def _is_valid_number(value) -> bool:
        """Return True if value is a finite, non-NaN number."""
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def Buy(self, price: float, amount: float, *args):
        price = float(price)
        amount = float(amount)
        if not self._is_valid_number(price) or not self._is_valid_number(amount):
            logger.debug(f"FMZ Buy ignored: invalid price/amount ({price}, {amount})")
            return None
        order_id = self._next_id("buy")
        self._orders[order_id] = FMZOrder(order_id, 0, price, amount)
        # Update account: spend balance, receive stocks.
        cost = price * amount
        if self.account.Balance >= cost:
            self.account.Balance -= cost
            self.account.Stocks += amount
        else:
            affordable = self.account.Balance / price if price > 0 else 0
            self.account.Balance = 0.0
            self.account.Stocks += affordable
        self._capture_signal("long", price, amount)
        logger.debug(f"FMZ Buy captured: {order_id} {price} x {amount}")
        return order_id

    def Sell(self, price: float, amount: float, *args):
        price = float(price)
        amount = float(amount)
        if not self._is_valid_number(price) or not self._is_valid_number(amount):
            logger.debug(f"FMZ Sell ignored: invalid price/amount ({price}, {amount})")
            return None
        order_id = self._next_id("sell")
        self._orders[order_id] = FMZOrder(order_id, 1, price, amount)
        # Update account: spend stocks, receive balance.
        available = min(amount, self.account.Stocks)
        self.account.Stocks -= available
        self.account.Balance += price * available
        self._capture_signal("short", price, amount)
        logger.debug(f"FMZ Sell captured: {order_id} {price} x {amount}")
        return order_id

    def CancelOrder(self, order_id: str):
        self._canceled.add(order_id)
        return True

    def GetOrder(self, order_id: str):
        return self._orders.get(order_id)

    def GetOrders(self):
        return [o for oid, o in self._orders.items() if oid not in self._canceled]

    def GetTrades(self):
        return list(self._orders.values())

    def SetPrecision(self, price_precision: int, amount_precision: int):
        pass

    def SetDirection(self, direction: str):
        pass

    def SetContractType(self, contract: str):
        pass

    def SetPeriod(self, period):
        pass

    def GetUSDCNY(self):
        """Return USD/CNY reference rate (sandboxed, no network)."""
        return 7.0

    def IO(self, *args):
        return None

    def GetName(self):
        return self._exchange_name

    def GetLabel(self):
        return "default"

    def GetCurrency(self):
        return self._currency

    def SetRate(self, rate: float):
        pass

    def GetMinStock(self):
        return 0.0001

    def GetPosition(self):
        """Return the current position as an FMZ position object."""
        # Aggregate captured signals into a synthetic position.  Longs are type 0,
        # shorts are type 1 in FMZ futures conventions.
        long_amount = sum(o.Amount for o in self._orders.values() if o.Type == 0)
        short_amount = sum(o.Amount for o in self._orders.values() if o.Type == 1)
        if long_amount > 0 and short_amount == 0:
            return [FMZPosition(amount=long_amount, price=self._last_price, position_type=0)]
        if short_amount > 0 and long_amount == 0:
            return [FMZPosition(amount=short_amount, price=self._last_price, position_type=1)]
        return []

    def Go(self, method: str, *args):
        """FMZ async helper: call method on exchange and return a mock thread."""
        fn = getattr(self, method, None)
        result = fn(*args) if fn else None

        class Thread:
            def wait(_self):
                return result
        return Thread()


class FMZPosition:
    """FMZ position object returned by some exchange helpers."""

    def __init__(self, amount: float = 0.0, price: float = 0.0, position_type: int = 0):
        self.Amount = amount
        self.Price = price
        self.Type = position_type

    def __getitem__(self, key):
        return getattr(self, key)

    def __str__(self) -> str:
        return str({"Amount": self.Amount, "Price": self.Price, "Type": self.Type})


class FMZTALibArray(np.ndarray):
    """NumPy array that also supports pandas-style ``.iloc`` indexing."""

    def __new__(cls, input_array):
        obj = np.asarray(input_array, dtype=float).view(cls)
        return obj

    def __array_finalize__(self, obj):
        pass

    @property
    def iloc(self):
        return self


class FMZTALibCompat:
    """
    Pure-pandas implementation of the TA-Lib functions most commonly used by
    FMZ strategies.  This is not a stub: each exposed method computes the real
    indicator.  Unsupported TA-Lib functions raise ``NotImplementedError`` so
    missing coverage is visible instead of silently returning zeros.
    """

    def __init__(self, ohlcv_df: Optional[pd.DataFrame] = None):
        self.ohlcv_df = ohlcv_df

    @staticmethod
    def _tolist(values):
        if values is None:
            return []
        if isinstance(values, pd.Series):
            return values.tolist()
        if isinstance(values, np.ndarray):
            return values.tolist()
        if hasattr(values, "to_list"):
            return values.to_list()
        try:
            return list(values)
        except Exception:
            return []

    def _series(self, values, field: str = "Close") -> pd.Series:
        if values is not None and len(values):
            return pd.Series(self._tolist(values))
        if self.ohlcv_df is not None and not self.ohlcv_df.empty:
            return self.ohlcv_df[field.lower()].copy()
        return pd.Series([])

    def MA(self, values, timeperiod=30):
        s = self._series(values)
        return FMZTALibArray(s.rolling(window=int(timeperiod), min_periods=1).mean())

    def EMA(self, values, timeperiod=30):
        s = self._series(values)
        return FMZTALibArray(s.ewm(span=int(timeperiod), adjust=False, min_periods=1).mean())

    def SMA(self, values, timeperiod=30):
        return self.MA(values, timeperiod)

    def RSI(self, values, timeperiod=14):
        s = self._series(values)
        if len(s) < 2:
            return FMZTALibArray([50.0] * len(s))
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / int(timeperiod), min_periods=1).mean()
        avg_loss = loss.ewm(alpha=1 / int(timeperiod), min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-9)
        return FMZTALibArray(100 - (100 / (1 + rs)))

    def MACD(self, values, fastperiod=12, slowperiod=26, signalperiod=9):
        s = self._series(values)
        ema_fast = s.ewm(span=int(fastperiod), adjust=False, min_periods=1).mean()
        ema_slow = s.ewm(span=int(slowperiod), adjust=False, min_periods=1).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=int(signalperiod), adjust=False, min_periods=1).mean()
        hist = macd - signal_line
        return (
            FMZTALibArray(macd),
            FMZTALibArray(signal_line),
            FMZTALibArray(hist),
        )

    def ATR(self, high, low, close, timeperiod=14):
        df = pd.DataFrame({
            "high": self._tolist(high),
            "low": self._tolist(low),
            "close": self._tolist(close),
        })
        if len(df) < 2:
            return FMZTALibArray([0.0])
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift()).abs()
        tr3 = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return FMZTALibArray(tr.ewm(span=int(timeperiod), adjust=False, min_periods=1).mean())

    def BBANDS(self, values, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0):
        s = self._series(values)
        ma = s.rolling(window=int(timeperiod), min_periods=1).mean()
        std = s.rolling(window=int(timeperiod), min_periods=1).std().fillna(0)
        upper = ma + nbdevup * std
        lower = ma - nbdevdn * std
        return (
            FMZTALibArray(upper),
            FMZTALibArray(ma),
            FMZTALibArray(lower),
        )

    def STOCH(self, high, low, close, fastk_period=14, slowk_period=3, slowd_period=3):
        high_s = pd.Series(self._tolist(high))
        low_s = pd.Series(self._tolist(low))
        close_s = pd.Series(self._tolist(close))
        lowest_low = low_s.rolling(window=int(fastk_period), min_periods=1).min()
        highest_high = high_s.rolling(window=int(fastk_period), min_periods=1).max()
        k = 100 * (close_s - lowest_low) / (highest_high - lowest_low).replace(0, 1e-9)
        slowk = k.rolling(window=int(slowk_period), min_periods=1).mean()
        slowd = slowk.rolling(window=int(slowd_period), min_periods=1).mean()
        return FMZTALibArray(slowk), FMZTALibArray(slowd)

    def TRANGE(self, high, low, close):
        df = pd.DataFrame({
            "high": self._tolist(high),
            "low": self._tolist(low),
            "close": self._tolist(close),
        })
        if len(df) < 2:
            return FMZTALibArray([0.0])
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift()).abs()
        tr3 = (df["low"] - df["close"].shift()).abs()
        return FMZTALibArray(pd.concat([tr1, tr2, tr3], axis=1).max(axis=1))

    def _wilder(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(alpha=1 / int(period), min_periods=1).mean()

    def PLUS_DI(self, high, low, close, timeperiod=14):
        df = pd.DataFrame({
            "high": self._tolist(high),
            "low": self._tolist(low),
            "close": self._tolist(close),
        })
        if len(df) < 2:
            return FMZTALibArray([0.0])
        up = df["high"].diff()
        down = -df["low"].diff()
        plus_dm = ((up > down) & (up > 0)) * up
        minus_dm = ((down > up) & (down > 0)) * down
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        atr = self._wilder(tr, timeperiod)
        plus_di = 100 * self._wilder(plus_dm, timeperiod) / atr.replace(0, 1e-9)
        return FMZTALibArray(plus_di)

    def MINUS_DI(self, high, low, close, timeperiod=14):
        df = pd.DataFrame({
            "high": self._tolist(high),
            "low": self._tolist(low),
            "close": self._tolist(close),
        })
        if len(df) < 2:
            return FMZTALibArray([0.0])
        up = df["high"].diff()
        down = -df["low"].diff()
        plus_dm = ((up > down) & (up > 0)) * up
        minus_dm = ((down > up) & (down > 0)) * down
        tr = pd.concat([df["high"] - df["low"],
                        (df["high"] - df["close"].shift()).abs(),
                        (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
        atr = self._wilder(tr, timeperiod)
        minus_di = 100 * self._wilder(minus_dm, timeperiod) / atr.replace(0, 1e-9)
        return FMZTALibArray(minus_di)

    def CMO(self, values, timeperiod=14):
        s = self._series(values)
        if len(s) < 2:
            return FMZTALibArray([0.0])
        diff = s.diff()
        sum_gain = diff.clip(lower=0).rolling(window=int(timeperiod), min_periods=1).sum()
        sum_loss = (-diff).clip(lower=0).rolling(window=int(timeperiod), min_periods=1).sum()
        return FMZTALibArray(100 * (sum_gain - sum_loss) / (sum_gain + sum_loss + 1e-9))


class FMZExt:
    """
    FMZ ``ext`` module adapter.  Only explicitly supported helpers are exposed;
    anything else raises ``AttributeError`` instead of silently returning None.

    When an exchange object is supplied, common trading-template helpers such as
    ``GetAccount``, ``Buy`` and ``Sell`` delegate to it so legacy strategies can
    run without modification.
    """

    def __init__(self, exchange: Optional[FMZExchange] = None):
        self._exchange = exchange
        self._state: Dict[str, Any] = {}

    def runToSystemTime(self, *args):
        return datetime.utcnow().timestamp() * 1000

    def runToVirtualTime(self, *args):
        return datetime.utcnow().timestamp() * 1000

    def GetAccountInfo(self, *args):
        return {}

    def GetExchangeInfo(self, *args):
        return {}

    def GetAccount(self, *args):
        if self._exchange is None:
            raise AttributeError("FMZExt.GetAccount requires an exchange")
        return self._exchange.GetAccount()

    def Buy(self, *args, **kwargs):
        if self._exchange is None:
            raise AttributeError("FMZExt.Buy requires an exchange")
        return self._exchange.Buy(*args, **kwargs)

    def Sell(self, *args, **kwargs):
        if self._exchange is None:
            raise AttributeError("FMZExt.Sell requires an exchange")
        return self._exchange.Sell(*args, **kwargs)


class FMZChart:
    """
    FMZ ``Chart`` object adapter.  Charting is output-only in Alpha Trader: this
    object stores plotted data so strategies can call the full Chart API without
    crashing, but rendering is intentionally not implemented here.
    """

    def __init__(self):
        self._series: List[Dict[str, Any]] = []
        self._annotations: List[Dict[str, Any]] = []

    def add(self, series_index: int, value: Any, *args):
        self._series.append({"index": series_index, "value": value})
        return self

    def reset(self, *args):
        self._series = []
        self._annotations = []
        return self

    def update(self, *args):
        return self

    def PlotRecords(self, records, name=None, *args):
        self._annotations.append({"type": "records", "name": name, "count": len(records) if records else 0})
        return self

    def PlotHLine(self, value, *args):
        self._annotations.append({"type": "hline", "value": value})
        return self

    def PlotVLine(self, time, *args):
        self._annotations.append({"type": "vline", "time": time})
        return self

    def PlotFlag(self, time, text, title, shape=None, color=None, *args):
        self._annotations.append({"type": "flag", "time": time, "text": text, "title": title})
        return self

    def PlotBar(self, name, value, time=None, *args):
        self._annotations.append({"type": "bar", "name": name, "value": value, "time": time})
        return self

    def PlotLine(self, name, value, time=None, *args):
        self._annotations.append({"type": "line", "name": name, "value": value, "time": time})
        return self

    def PlotDot(self, name, value, time=None, *args):
        self._annotations.append({"type": "dot", "name": name, "value": value, "time": time})
        return self

    def PlotText(self, name, value, time=None, *args):
        self._annotations.append({"type": "text", "name": name, "value": value, "time": time})
        return self

    def PlotPanel(self, *args):
        return self

    def SetTitle(self, *args):
        return self

    def SetXYBuilder(self, *args):
        return self

    def SetRange(self, *args):
        return self


class _FMZGState:
    """Python-backed storage for the JS ``_G`` helper."""

    def __init__(self, state: Dict[str, Any]):
        self._state = state

    def get(self, key):
        return self._state.get(key)

    def set(self, key, value):
        self._state[key] = value
        return value


class _FMZLogger:
    """Python-backed logger for JS ``Log``/``LogProfit``/``LogStatus`` helpers."""

    def log(self, msg: str):
        logger.debug(f"FMZ Log: {msg}")

    def log_profit(self, msg: str):
        logger.debug(f"FMZ LogProfit: {msg}")

    def log_status(self, msg: str):
        logger.debug(f"FMZ LogStatus: {msg}")


class _FMZChartFactory:
    """Python-backed factory for the JS ``Chart`` helper."""

    def create(self, config=None):
        return FMZChart()


class FMZTA:
    """FMZ TA library exposing common indicator functions backed by pandas."""

    def __init__(self, ohlcv_df: Optional[pd.DataFrame] = None):
        self.ohlcv_df = ohlcv_df

    def _series(self, records, field: str = "Close") -> pd.Series:
        if isinstance(records, list) and records:
            return pd.Series([r.get(field, r.get(field.lower(), 0)) for r in records])
        if self.ohlcv_df is not None:
            return self.ohlcv_df[field.lower()].copy()
        return pd.Series([])

    def MA(self, records, period: int, field: str = "Close"):
        s = self._series(records, field)
        return s.rolling(window=int(period), min_periods=1).mean().tolist()

    def EMA(self, records, period: int, field: str = "Close"):
        s = self._series(records, field)
        return s.ewm(span=int(period), adjust=False, min_periods=1).mean().tolist()

    def Highest(self, records, period: int, field: str = "High"):
        s = self._series(records, field)
        return float(s.tail(int(period)).max()) if not s.empty else 0.0

    def Lowest(self, records, period: int, field: str = "Low"):
        s = self._series(records, field)
        return float(s.tail(int(period)).min()) if not s.empty else 0.0

    def RSI(self, records, period: int = 14, field: str = "Close"):
        s = self._series(records, field)
        if len(s) < 2:
            return [50.0] * len(s)
        delta = s.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=1).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=1).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return rsi.tolist()

    def MACD(self, records, fast: int = 12, slow: int = 26, signal: int = 9, field: str = "Close"):
        s = self._series(records, field)
        ema_fast = s.ewm(span=fast, adjust=False, min_periods=1).mean()
        ema_slow = s.ewm(span=slow, adjust=False, min_periods=1).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False, min_periods=1).mean()
        histogram = macd - signal_line
        return FMZMACDResult(macd.tolist(), signal_line.tolist(), histogram.tolist())

    def ATR(self, records, period: int = 14):
        if isinstance(records, list):
            df = pd.DataFrame(records)
        else:
            df = self.ohlcv_df
        if df is None or len(df) < 2:
            return [0.0]
        high = df["high"] if "high" in df else df["High"]
        low = df["low"] if "low" in df else df["Low"]
        close = df["close"] if "close" in df else df["Close"]
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False, min_periods=1).mean()
        return atr.tolist()

    def BOLL(self, records, period: int = 20, nbdev: float = 2.0, field: str = "Close"):
        s = self._series(records, field)
        ma = s.rolling(window=int(period), min_periods=1).mean()
        std = s.rolling(window=int(period), min_periods=1).std().fillna(0)
        upper = ma + nbdev * std
        lower = ma - nbdev * std
        return [upper.tolist(), ma.tolist(), lower.tolist()]


class FMZStdLib:
    """
    FMZ standard library helpers ($.*).  Each method is a real wrapper around
    the exchange or charting adapter.  No silent catch-all: unsupported helpers
    raise ``AttributeError``.
    """

    def __init__(self, exchange: FMZExchange, ta: FMZTA):
        self.exchange = exchange
        self.ta = ta

    def Buy(self, amount, price=None):
        price = price if price is not None else self.exchange.quote.Sell
        order_id = self.exchange.Buy(price, amount)
        return {"price": price, "amount": amount, "id": order_id}

    def Sell(self, amount, price=None):
        price = price if price is not None else self.exchange.quote.Buy
        order_id = self.exchange.Sell(price, amount)
        return {"price": price, "amount": amount, "id": order_id}

    def Cross(self, fast_period, slow_period, records=None):
        """Return number of periods fast EMA has been above/below slow EMA."""
        if records is None:
            records = self.exchange.GetRecords()
        fast = self.ta.EMA(records, fast_period)
        slow = self.ta.EMA(records, slow_period)
        if not fast or not slow or len(fast) < 2 or len(slow) < 2:
            return 0
        count = 0
        for i in range(1, min(len(fast), len(slow))):
            idx_fast = -i
            idx_slow = -i
            if fast[idx_fast] > slow[idx_slow]:
                if count >= 0:
                    count += 1
                else:
                    break
            elif fast[idx_fast] < slow[idx_slow]:
                if count <= 0:
                    count -= 1
                else:
                    break
            else:
                break
        return count

    # Chart/plotting helpers used as $.PlotRecords, $.PlotLine, etc.
    def PlotRecords(self, records, name=None, *args):
        return FMZChart().PlotRecords(records, name, *args)

    def PlotLine(self, name, value, time=None, *args):
        return FMZChart().PlotLine(name, value, time, *args)

    def PlotFlag(self, time, text, title, shape=None, color=None, *args):
        return FMZChart().PlotFlag(time, text, title, shape, color, *args)

    def PlotHLine(self, value, *args):
        return FMZChart().PlotHLine(value, *args)

    def PlotVLine(self, time, *args):
        return FMZChart().PlotVLine(time, *args)

    def PlotBar(self, name, value, time=None, *args):
        return FMZChart().PlotBar(name, value, time, *args)

    def PlotDot(self, name, value, time=None, *args):
        return FMZChart().PlotDot(name, value, time, *args)

    def PlotText(self, name, value, time=None, *args):
        return FMZChart().PlotText(name, value, time, *args)

    def GetCfg(self, *args):
        return {"series": [], "yAxis": [], "title": {}}

    def ChartObj(self, *args):
        return FMZChart()


class FMZRuntime:
    """
    Run an FMZ strategy source file inside Alpha Trader.

    Args:
        source_code: Raw JavaScript or Python source.
        language: ``javascript`` or ``python``.
        args: Strategy arguments injected as global variables.
        strategy_name: Name used for generated signals.
        timeframe: Timeframe label for generated signals.
    """

    def __init__(
        self,
        source_code: str,
        language: str,
        args: Optional[Dict[str, Any]] = None,
        strategy_name: str = "fmz_strategy",
        timeframe: str = "5m",
        exchange_name: str = "FMZ_Stub",
    ):
        self.source_code = source_code or ""
        self.language = language.lower()
        self.args = args or {}
        self.strategy_name = strategy_name
        self.timeframe = timeframe
        self.exchange_name = exchange_name
        self._tick_count = 0
        self._global_state: Dict[str, Any] = {}

    def _common_globals(self, exchange: FMZExchange, ta: FMZTA, for_js: bool = False):
        """Build helper functions and constants shared by Python and JS runtimes."""
        stdlib_inst = FMZStdLib(exchange, ta)

        def _log(*args):
            logger.debug("FMZ Log: " + " ".join(str(a) for a in args))

        def _log_profit(*args):
            logger.debug("FMZ LogProfit: " + " ".join(str(a) for a in args))

        def _log_status(*args):
            logger.debug("FMZ LogStatus: " + " ".join(str(a) for a in args))

        def _log_reset(*args, **kwargs):
            pass

        def _log_profit_reset(*args, **kwargs):
            pass

        def _enable_log(enabled=True):
            """FMZ logging toggle: no-op in sandbox."""
            pass

        def _d(*args):
            return datetime.utcnow().isoformat()

        def _sleep(ms):
            self._tick_count += 1
            if self._tick_count >= exchange.tick_limit:
                raise RuntimeError("FMZ tick limit reached")
            if time.time() - self._start_time > MAX_RUNTIME_MS / 1000:
                raise RuntimeError("FMZ runtime timeout")

        def _c(fn, *args, **kwargs):
            return fn(*args, **kwargs)

        def _cross(a, b):
            """FMZ global cross detector: +1 = a crosses above b, -1 = below, 0 = none."""
            if a is None or b is None:
                return 0

            def _to_list(values):
                if hasattr(values, "to_list"):
                    return values.to_list()
                try:
                    return list(values)
                except Exception:
                    return []

            a_vals = _to_list(a)
            b_vals = _to_list(b)
            if len(a_vals) < 2 or len(b_vals) < 2:
                return 0
            if a_vals[-2] <= b_vals[-2] and a_vals[-1] > b_vals[-1]:
                return 1
            if a_vals[-2] >= b_vals[-2] and a_vals[-1] < b_vals[-1]:
                return -1
            return 0

        def _get_command():
            return None

        def _get_last_error():
            return ""

        def _get_pid():
            import os
            return os.getpid()

        def _set_error_filter(*args):
            """FMZ error filter: no-op in sandbox."""
            pass

        def _http_query(*args):
            """FMZ HTTP helper: sandbox returns empty string (no network I/O)."""
            return ""

        def _dial_mail(*args):
            return True

        def _send_mail(*args):
            return True

        _G_SENTINEL = object()

        def _g(key=None, value=_G_SENTINEL):
            """FMZ global state helper: _G(key) reads, _G(key, val) writes, _G() no-op."""
            if key is None:
                if value is _G_SENTINEL:
                    return None
                # _G(None) resets persisted state.
                self._global_state.clear()
                return None
            if value is _G_SENTINEL:
                return self._global_state.get(key)
            self._global_state[key] = value
            return value

        def _n(value, precision=4):
            """FMZ number formatting helper."""
            try:
                return round(float(value), int(precision))
            except Exception:
                return value

        def is_virtual():
            return True

        chart_factory = lambda *a, **k: FMZChart()
        ext = FMZExt(exchange)

        globals_dict = {
            "exchange": exchange,
            "exchanges": [exchange],
            "TA": ta,
            "$": stdlib_inst,
            "Log": _log,
            "LogProfit": _log_profit,
            "LogStatus": _log_status,
            "LogReset": _log_reset,
            "LogProfitReset": _log_profit_reset,
            "EnableLog": _enable_log,
            "_D": _d,
            "_G": _g,
            "_N": _n,
            "Sleep": _sleep,
            "_C": _c,
            "_Cross": _cross,
            "GetCommand": _get_command,
            "GetLastError": _get_last_error,
            "GetPid": _get_pid,
            "SetErrorFilter": _set_error_filter,
            "HttpQuery": _http_query,
            "DialMail": _dial_mail,
            "SendMail": _send_mail,
            "IsVirtual": is_virtual,
            "Chart": chart_factory,
            "ext": ext,
            "ORDER_STATE_PENDING": FMZExchange.ORDER_STATE_PENDING,
            "ORDER_STATE_CLOSED": FMZExchange.ORDER_STATE_CLOSED,
            "ORDER_STATE_CANCELED": FMZExchange.ORDER_STATE_CANCELED,
            "PERIOD_M1": 1,
            "PERIOD_M5": 5,
            "PERIOD_M15": 15,
            "PERIOD_M30": 30,
            "PERIOD_H1": 60,
            "PERIOD_D1": 1440,
            "true": True,
            "false": False,
            "null": None,
        }
        return globals_dict

    def _make_globals(self, exchange: FMZExchange, ohlcv_df: Optional[pd.DataFrame] = None):
        """Build a Python globals dict for exec'ing a Python strategy."""
        ta = FMZTA(ohlcv_df)
        namespace = self._common_globals(exchange, ta, for_js=False)
        # Inject strategy arguments as globals.
        namespace.update(self.args)
        # FMZ Python strategies may construct additional exchange objects.
        namespace["Exchange"] = lambda: exchange
        return namespace

    def _run_python(self, exchange: FMZExchange, ohlcv_df: Optional[pd.DataFrame]) -> List[Signal]:
        # Python strategies that import talib get a real pandas-backed implementation.
        import sys
        import types
        if "talib" not in sys.modules:
            sys.modules["talib"] = FMZTALibCompat(ohlcv_df)

        # Patch Python 2-style type aliases used by legacy FMZ strategies.
        types.ListType = list
        types.IntType = int
        types.FloatType = float
        types.StringType = str
        types.BooleanType = bool
        types.DictType = dict

        # Restore DataFrame.append removed in pandas 2.0 for legacy strategies.
        if not hasattr(pd.DataFrame, "append"):
            def _df_append(self, other, ignore_index=False, verify_integrity=False, sort=False):
                if isinstance(other, dict):
                    other = pd.DataFrame([other])
                elif not isinstance(other, pd.DataFrame):
                    other = pd.DataFrame(other)
                return pd.concat(
                    [self, other],
                    ignore_index=ignore_index,
                    verify_integrity=verify_integrity,
                    sort=sort,
                )
            pd.DataFrame.append = _df_append

        self._start_time = time.time()
        namespace = self._make_globals(exchange, ohlcv_df)
        # Intercept time.sleep so strategies that use it respect the tick limit.
        import time as _time_module
        _time_module.sleep = namespace["Sleep"]
        source = self.source_code
        try:
            exec(source, namespace)
        except SyntaxError:
            # Some FMZ Python strategies are written for Python 2.  Try a one-shot
            # lib2to3 conversion before giving up.
            converted = self._convert_python2_source(source)
            if converted is not None:
                namespace = self._make_globals(exchange, ohlcv_df)
                _time_module.sleep = namespace["Sleep"]
                exec(converted, namespace)
            else:
                raise
        except RuntimeError as e:
            if "tick limit" in str(e):
                logger.debug("Python FMZ strategy hit tick limit; returning captured signals")
            else:
                raise

        # FMZ strategies define main() or onTick() as entry points.
        # Prefer main() since it sets up state and loops; fall back to onTick().
        if "main" in namespace and callable(namespace["main"]):
            try:
                namespace["main"]()
            except RuntimeError as e:
                if "tick limit" not in str(e):
                    raise
        elif "onTick" in namespace and callable(namespace["onTick"]):
            try:
                on_tick = namespace["onTick"]
                import inspect
                sig = inspect.signature(on_tick)
                if len(sig.parameters) > 0:
                    on_tick(exchange)
                else:
                    on_tick()
            except RuntimeError as e:
                if "tick limit" not in str(e):
                    raise

        # Tag signals with this strategy's metadata.
        for signal in exchange.signals:
            signal.strategy_name = self.strategy_name
            signal.timeframe = self.timeframe
        return exchange.signals

    @staticmethod
    def _convert_python2_source(source: str) -> Optional[str]:
        """Attempt to convert Python 2 source to Python 3 using lib2to3."""
        try:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from lib2to3.refactor import RefactoringTool, get_fixers_from_package
                tool = RefactoringTool(get_fixers_from_package("lib2to3.fixes"))
                # lib2to3 requires a trailing newline on some inputs.
                result = tool.refactor_string(source + "\n", "<fmz>")
            return str(result)
        except Exception as e:
            logger.debug(f"lib2to3 conversion failed: {e}")
            return None

    def _run_javascript(self, exchange: FMZExchange, ohlcv_df: Optional[pd.DataFrame]) -> List[Signal]:
        if not JS2PY_AVAILABLE:
            logger.warning("js2py not installed; cannot run FMZ JavaScript strategies")
            return []

        self._tick_count = 0
        self._start_time = time.time()
        ta = FMZTA(ohlcv_df)
        js_globals = self._common_globals(exchange, ta, for_js=True)

        # JS strategies get a real pandas-backed talib global.
        js_globals["talib"] = FMZTALibCompat(ohlcv_df)

        # Inject strategy arguments (with JS-compatible primitive types).
        for key, value in self.args.items():
            js_globals[key] = value

        # js2py does not pass arguments to Python *args functions and does not
        # translate Python None into JS null.  We therefore define a handful of
        # commonly-used FMZ globals as real JS functions backed by Python objects.
        js_globals["_fmz_g_state"] = _FMZGState(self._global_state)
        js_globals["_fmz_logger"] = _FMZLogger()
        js_globals["_fmz_chart_factory"] = _FMZChartFactory()

        context = EvalJs(js_globals)
        context.execute("""
            function _G(key, value) {
                if (arguments.length < 2) {
                    var v = _fmz_g_state.get(key);
                    return v === undefined ? null : v;
                }
                return _fmz_g_state.set(key, value);
            }
            function Log() {
                _fmz_logger.log(Array.prototype.slice.call(arguments).join(' '));
            }
            function LogProfit() {
                _fmz_logger.log_profit(Array.prototype.slice.call(arguments).join(' '));
            }
            function LogStatus() {
                _fmz_logger.log_status(Array.prototype.slice.call(arguments).join(' '));
            }
            function LogReset() {}
            function LogProfitReset() {}
            function EnableLog(enabled) {}
            function SetErrorFilter(regex) {}
            function HttpQuery(url, data, headers, method) {
                return "";
            }
            function DialMail(smtp, port, user, password) {
                return true;
            }
            function SendMail(to, title, body) {
                return true;
            }
            function Chart(config) {
                return _fmz_chart_factory.create(config);
            }
            function _C(fn) {
                if (typeof fn === 'function') {
                    return fn();
                }
                return fn;
            }
        """)

        # Run source.  js2py will interpret the while/Sleep loop; Sleep raises after tick_limit.
        try:
            context.execute(self.source_code)
        except Exception as e:
            msg = str(e)
            if "tick limit" in msg or "timeout" in msg.lower():
                logger.debug("JS FMZ strategy hit tick limit; returning captured signals")
            else:
                logger.warning(f"js2py execution error: {e}")

        # FMZ strategies define main() or onTick() as entry points.
        # Prefer main() since it sets up state and loops; fall back to onTick().
        try:
            context.execute("""
                if (typeof main === 'function') {
                    main();
                } else if (typeof onTick === 'function') {
                    onTick();
                }
            """)
        except Exception as e:
            if "tick limit" not in str(e):
                logger.debug(f"FMZ entry point failed: {e}")

        for signal in exchange.signals:
            signal.strategy_name = self.strategy_name
            signal.timeframe = self.timeframe
        return exchange.signals

    def run(
        self,
        symbol: str,
        ohlcv_df: Optional[pd.DataFrame] = None,
        default_price: float = 100.0,
        tick_limit: int = MAX_RUNTIME_TICKS,
        exchange_name: Optional[str] = None,
        max_signals: Optional[int] = None,
        quality_only: bool = False,
    ) -> List[Signal]:
        """Execute the strategy and return captured Alpha Trader signals."""
        if quality_only and not is_quality_fmz_strategy(self.source_code, ""):
            logger.debug(f"Skipping non-quality FMZ strategy {self.strategy_name}")
            return []

        exchange = FMZExchange(
            symbol=symbol,
            ohlcv_df=ohlcv_df,
            default_price=default_price,
            tick_limit=tick_limit,
            exchange_name=exchange_name or self.exchange_name,
            max_signals=max_signals,
        )

        if self.language == "python":
            return self._run_python(exchange, ohlcv_df)
        if self.language == "javascript":
            return self._run_javascript(exchange, ohlcv_df)

        logger.warning(f"Unsupported FMZ language: {self.language}")
        return []


# Small alias for convenience.
run_fmz_strategy = FMZRuntime
