"""Inspect the FMZ strategies that produced signals in the focus smoke test."""
import re
from strategies.fmz_parser import FMZParser

SIGNAL_STRATEGIES = [
    "fmz_50_7648",
    "fmz_final_formula_by_tradershaman",
    "fmz_martingale_strategy1",
    "fmz_python",
    "fmz_python_efaf",
    "fmz_getminstock",
    "fmz_simple_iceberg_order_to_buy",
    "fmz_strategy_4fea",
    "fmz_alpha",
    "fmz_strategy_180b",
    "fmz_strategy_6c60",
    "fmz_strategy_ed23",
    "fmz_strategy_4872",
    "fmz_100usdt_100usdt_invested_every_week_regular_fixed_investment",
    "fmz_100usdt_100usdt_invested_every_week_regular_variable_investment",
    "fmz_bithumb_ordersdetail",
    "fmz_strategy_9ad7",
    "fmz_hedge_on_two_contracts",
    "fmz_strategy_dbe3",
    "fmz_simple_iceberg_order_to_buy_copy",
    "fmz_buy_then_sell_ping_pong_strategy",
]

INDICATORS_RE = re.compile(
    r"\b(TA-Lib|talib|TA\.|Indicator|MACD|RSI|EMA|SMA|ATR|Bollinger|KDJ|KD\\b|DMI|ADX|"
    r"CCI|OBV|Williams|Stoch|Momentum|Ichimoku|SAR|EMA[_ ]cross|MA[_ ]cross|"
    r"golden[_ ]cross|death[_ ]cross|breakout|support|resistance|mavg|moving.?average|"
    r"mean.?reversion|trend|momentum|KDJE|MA5|MA10|MA20|MA30|MA60|MA120)\b",
    re.IGNORECASE,
)

fmz_parser = FMZParser()
catalog = fmz_parser.build_catalog()
lookup = {e.python_identifier: e for e in catalog}

for name in SIGNAL_STRATEGIES:
    entry = lookup.get(name)
    if not entry:
        print(f"\n{name}: NOT FOUND")
        continue
    code = entry.source_code or ""
    desc = entry.description or ""
    hits = INDICATORS_RE.findall(code + "\n" + desc)
    print(f"\n{'='*60}")
    print(f"identifier : {name}")
    print(f"name       : {entry.name}")
    print(f"language   : {entry.source_language}")
    print(f"lines      : {len(code.splitlines())}")
    print(f"indicators : {sorted(set(hits))}")
    print(f"description: {desc[:280].replace(chr(10), ' ')}")
    snippet = code[:600].replace(chr(10), "\n  ")
    print(f"code head  :\n  {snippet}")
