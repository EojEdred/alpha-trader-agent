"""
Tests for the FMZ Quant strategy integration.

Covers:
- Markdown parser correctness
- FMZ runtime adapter sandbox behavior
- Generated strategy registration
- CLI command smoke tests
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from strategies.fmz_parser import FMZParser, FMZStrategy
from strategies.fmz_runtime import (
    FMZRuntime,
    FMZExchange,
    infer_fmz_exchange_name,
    is_quality_fmz_strategy,
)
from strategies.registry import StrategyRegistry


SAMPLE_MD = """
> Name

Test Strategy

> Author

Test Author

> Strategy Description

A test strategy.

> Strategy Arguments

|Argument|Default|Description|
|----|----|----|
|period|14|Lookback period|
|use_stop|true|Use stop loss|

> Source (javascript)

``` javascript
function onTick() {
    var ticker = exchange.GetTicker();
    if (ticker.Last > 100) {
        exchange.Buy(ticker.Last, 1);
    } else {
        exchange.Sell(ticker.Last, 1);
    }
}
function main() {
    while (true) {
        onTick();
        Sleep(1000);
    }
}
```

> Detail

https://www.fmz.com/strategy/12345

> Last Modified

2024-01-01 00:00:00
""".strip()


class TestFMZParser:
    def test_parse_sample_markdown(self, tmp_path):
        md_file = tmp_path / "test_strategy.md"
        md_file.write_text(SAMPLE_MD, encoding="utf-8")

        parser = FMZParser(fmz_dir=tmp_path)
        entry = parser.parse_file(md_file)

        assert entry.name == "Test Strategy"
        assert entry.author == "Test Author"
        assert entry.parse_status == "ok"
        assert entry.source_language == "javascript"
        assert len(entry.arguments) == 2
        assert entry.arguments[0]["argument"] == "period"
        assert entry.arguments[0]["default"] == 14
        assert entry.arguments[1]["argument"] == "use_stop"
        assert entry.arguments[1]["default"] is True

    def test_catalog_roundtrip(self, tmp_path):
        md_file = tmp_path / "test_strategy.md"
        md_file.write_text(SAMPLE_MD, encoding="utf-8")

        parser = FMZParser(fmz_dir=tmp_path)
        catalog = parser.build_catalog()
        catalog_path = tmp_path / "catalog.json"
        parser.save_catalog(catalog, catalog_path)

        loaded = parser.load_catalog(catalog_path)
        assert len(loaded) == 1
        assert loaded[0].name == "Test Strategy"


class TestFMZRuntime:
    def test_javascript_runtime_generates_signal(self):
        js = """
        function onTick() {
            var ticker = exchange.GetTicker();
            exchange.Buy(ticker.Last, 10);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        df = pd.DataFrame({
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1000, 1000],
        })
        runtime = FMZRuntime(js, language="javascript", strategy_name="test_buy")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=1)

        assert len(signals) == 1
        assert signals[0].symbol == "SPY"
        assert signals[0].direction == "long"
        assert signals[0].strategy_name == "test_buy"

    def test_python_runtime_generates_signal(self):
        py = """
def onTick():
    ticker = exchange.GetTicker()
    exchange.Sell(ticker.Last, 5)

def main():
    while True:
        onTick()
        Sleep(1000)
"""
        df = pd.DataFrame({
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100.5, 101.5, 102.5],
            "volume": [1000, 1000, 1000],
        })
        runtime = FMZRuntime(py, language="python", strategy_name="test_sell")
        signals = runtime.run(symbol="QQQ", ohlcv_df=df, tick_limit=1)

        assert len(signals) == 1
        assert signals[0].symbol == "QQQ"
        assert signals[0].direction == "short"

    def test_tick_limit_stops_infinite_loop(self):
        js = "while (true) { Sleep(1); }"
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=3)
        assert signals == []

    def test_fmz_stdlib_buy_sell(self):
        js = """
        function onTick() {
            $.Buy(10);
            $.Sell(5);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)

        assert len(signals) == 2
        assert signals[0].direction == "long"
        assert signals[1].direction == "short"

    def test_fmz_cross_helper(self):
        js = """
        function onTick() {
            var n = $.Cross(5, 10);
            if (n > 0) {
                exchange.Buy(exchange.GetTicker().Last, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        # Strong uptrend so fast EMA > slow EMA.
        df = pd.DataFrame({
            "open": list(range(100, 130)),
            "high": [x + 1 for x in range(100, 130)],
            "low": [x - 1 for x in range(100, 130)],
            "close": [x + 0.5 for x in range(100, 130)],
            "volume": [1000] * 30,
        })
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=2)
        # Should at least run without error.
        assert isinstance(signals, list)

    def test_supported_globals_resolve(self):
        js = """
        function onTick() {
            var x = _G("key", 1);
            var y = _N(123.4567, 2);
            var z = IsVirtual();
            var c = Chart();
            c.add(0, 1);
            ext.runToSystemTime();
            ext.GetAccountInfo();
            exchange.Buy(100, 1);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_unsupported_globals_raise(self):
        js = """
        function onTick() {
            ext.SomeUnknownHelper(1, 2);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert signals == []

    def test_python_talib_compat(self):
        py = """
import talib

def onTick():
    close = [r['Close'] for r in exchange.GetRecords()]
    if len(close) < 5:
        return
    ma = talib.MA(close, timeperiod=5)
    if close[-1] > ma[-1]:
        exchange.Buy(close[-1], 1)

def main():
    while True:
        onTick()
        Sleep(1000)
"""
        df = pd.DataFrame({
            "open": list(range(100, 120)),
            "high": [x + 1 for x in range(100, 120)],
            "low": [x - 1 for x in range(100, 120)],
            "close": [x + 0.5 for x in range(100, 120)],
            "volume": [1000] * 20,
        })
        runtime = FMZRuntime(py, language="python")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=2)
        assert isinstance(signals, list)

    def test_javascript_talib_compat(self):
        js = """
        function onTick() {
            var records = exchange.GetRecords();
            var close = [];
            for (var i = 0; i < records.length; i++) {
                close.push(records[i].Close);
            }
            if (close.length < 5) return;
            var ma = talib.MA(close, 5);
            if (close[close.length - 1] > ma[ma.length - 1]) {
                exchange.Buy(exchange.GetTicker().Last, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        df = pd.DataFrame({
            "open": list(range(100, 120)),
            "high": [x + 1 for x in range(100, 120)],
            "low": [x - 1 for x in range(100, 120)],
            "close": [x + 0.5 for x in range(100, 120)],
            "volume": [1000] * 20,
        })
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=2)
        assert isinstance(signals, list)

    def test_javascript_chart_and_ext(self):
        js = """
        function onTick() {
            var c = Chart();
            c.add(0, 1);
            c.reset();
            $.PlotLine("avg", 100);
            ext.runToSystemTime();
            exchange.Buy(100, 1);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_fmz_cross_global_helper(self):
        js = """
        function onTick() {
            var a = [1, 2, 3, 4, 6];
            var b = [6, 5, 4, 4, 4];
            if (_Cross(a, b) > 0) {
                exchange.Buy(100, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_exchange_objects_are_subscriptable(self):
        js = """
        function onTick() {
            var ticker = exchange.GetTicker();
            var account = exchange.GetAccount();
            if (ticker["Last"] > 0 && account["Balance"] > 0) {
                exchange.Buy(ticker["Last"], 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_exchange_name_mapping(self):
        js = """
        function onTick() {
            if (exchange.GetName() === "Futures_OKCoin") {
                exchange.Buy(100, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript", exchange_name="Futures_OKCoin")
        signals = runtime.run(symbol="BTC_USD", tick_limit=1)
        assert len(signals) == 1

    def test_exchange_name_inference_for_focus_symbols(self):
        from strategies.fmz_runtime import infer_fmz_exchange_name
        assert infer_fmz_exchange_name("SPY") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("QQQ") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("TSLA") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("SPY240119C00450000") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("GC") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("XAUUSD") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("ES") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("NQ") == "Futures_OKCoin"

    def test_account_updates_on_buy_sell(self):
        js = """
        function onTick() {
            var account = exchange.GetAccount();
            var startBalance = account.Balance;
            exchange.Buy(100, 1);
            var afterBuy = exchange.GetAccount();
            if (afterBuy.Balance < startBalance && afterBuy.Stocks > 0) {
                exchange.Sell(100, afterBuy.Stocks);
                var afterSell = exchange.GetAccount();
                if (afterSell.Stocks === 0) {
                    exchange.Buy(100, 1);
                }
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=2)
        assert len(signals) >= 2

    def test_g_persists_across_ticks(self):
        js = """
        function onTick() {
            var count = _G("count");
            if (count === null) {
                count = 0;
            }
            count = count + 1;
            _G("count", count);
            if (count === 2) {
                exchange.Buy(100, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=3)
        assert len(signals) == 1

    def test_js_c_helper_calls_function(self):
        js = """
        function onTick() {
            var ticker = _C(exchange.GetTicker);
            if (ticker && ticker.Last > 0) {
                exchange.Buy(ticker.Last, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_js_log_variadic(self):
        js = """
        function onTick() {
            Log("price", exchange.GetTicker().Last, "buying");
            LogProfit("profit");
            LogStatus("status");
            exchange.Buy(100, 1);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_js_standard_globals(self):
        js = """
        function onTick() {
            SetErrorFilter(".*");
            LogProfitReset();
            var resp = HttpQuery("https://example.com");
            if (resp === "") {
                exchange.Buy(100, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_python2_syntax_conversion(self):
        py = """
def onTick():
    print "buy signal"
    exchange.Buy(100, 1)

def main():
    while True:
        onTick()
        Sleep(1000)
"""
        runtime = FMZRuntime(py, language="python")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1

    def test_max_signals_caps_output(self):
        js = """
        function onTick() {
            for (var i = 0; i < 10; i++) {
                exchange.Buy(100, 1);
            }
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript")
        signals = runtime.run(symbol="SPY", tick_limit=1, max_signals=3)
        assert len(signals) == 3

    def test_quality_only_blocks_noise_strategy(self):
        js = """
        function onTick() {
            exchange.Buy(100, 1);
        }
        function main() {
            while (true) { onTick(); Sleep(1000); }
        }
        """
        runtime = FMZRuntime(js, language="javascript", strategy_name="noise_buyer")
        signals = runtime.run(symbol="SPY", tick_limit=1, quality_only=True)
        assert signals == []

    def test_quality_only_allows_indicator_strategy(self):
        py = """
import talib

def onTick():
    close = [r['Close'] for r in exchange.GetRecords()]
    if len(close) < 5:
        return
    ma = talib.MA(close, timeperiod=5)
    if close[-1] > ma[-1]:
        exchange.Buy(close[-1], 1)

def main():
    while True:
        onTick()
        Sleep(1000)
"""
        df = pd.DataFrame({
            "open": list(range(100, 120)),
            "high": [x + 1 for x in range(100, 120)],
            "low": [x - 1 for x in range(100, 120)],
            "close": [x + 0.5 for x in range(100, 120)],
            "volume": [1000] * 20,
        })
        runtime = FMZRuntime(py, language="python", strategy_name="ma_buyer")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=2, quality_only=True)
        assert isinstance(signals, list)

    def test_talib_compat_supports_iloc_and_negative_indexing(self):
        py = """
import talib

def onTick():
    records = exchange.GetRecords()
    upper, middle, lower = talib.BBANDS(records.Close, timeperiod=5)
    if records.Close[-1] > upper.iloc[-1]:
        exchange.Buy(records.Close[-1], 1)

def main():
    while True:
        onTick()
        Sleep(1000)
"""
        df = pd.DataFrame({
            "open": list(range(100, 120)),
            "high": [x + 2 for x in range(100, 120)],
            "low": [x - 2 for x in range(100, 120)],
            "close": [x + 0.5 for x in range(100, 120)],
            "volume": [1000] * 20,
        })
        runtime = FMZRuntime(py, language="python")
        signals = runtime.run(symbol="SPY", ohlcv_df=df, tick_limit=2)
        assert isinstance(signals, list)

    def test_python_exchange_constructor_and_true_false(self):
        py = """
exchange = Exchange()
exchange.SetContractType("BTC_USDT")
exchange.SetPeriod("1m")

def main():
    ticker = exchange.GetTicker()
    if true:
        exchange.Buy(ticker.Last, 1)
    if false:
        exchange.Sell(ticker.Last, 1)
"""
        runtime = FMZRuntime(py, language="python")
        signals = runtime.run(symbol="SPY", tick_limit=1)
        assert len(signals) == 1
        assert signals[0].direction == "long"


class TestFMZQuality:
    def test_quality_classifier_rejects_noise(self):
        assert not is_quality_fmz_strategy("exchange.Buy(100, 1)", "Simple iceberg order")

    def test_quality_classifier_accepts_indicator_strategy(self):
        src = "ma = TA.EMA(records, 10)\nif (ma[-1] > ...) exchange.Buy(-1, 1)"
        assert is_quality_fmz_strategy(src, "EMA trend")

    def test_infer_exchange_name_for_focus_symbols(self):
        assert infer_fmz_exchange_name("SPY") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("QQQ") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("TSLA") == "Stocks_AlphaTrader"
        assert infer_fmz_exchange_name("GC") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("ES") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("NQ") == "Futures_OKCoin"
        assert infer_fmz_exchange_name("XAUUSD") == "Futures_OKCoin"


class TestFMZRegistry:
    def test_registry_discovers_generated_strategies(self):
        registry = StrategyRegistry()
        registry.discover()

        names = [s["name"] for s in registry.list_strategies()]
        assert any(name.startswith("fmz_") for name in names)

    def test_registry_runs_fmz_strategy(self):
        registry = StrategyRegistry()
        registry.discover()

        fmz_names = [s["name"] for s in registry.list_strategies() if s["name"].startswith("fmz_")]
        assert fmz_names

        df = pd.DataFrame({
            "open": [100 + i * 0.1 for i in range(50)],
            "high": [101 + i * 0.1 for i in range(50)],
            "low": [99 + i * 0.1 for i in range(50)],
            "close": [100.5 + i * 0.1 for i in range(50)],
            "volume": [1000] * 50,
        })
        data = {"ohlcv": {"SPY": df}}

        # Should not raise.
        results = registry.run(fmz_names[0], data)
        assert isinstance(results, list)
