"""Classify FMZ strategies that produced signals in the focus smoke test."""
import json
import re
from pathlib import Path
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

# Indicator/quality keywords (case-insensitive)
QUALITY_RE = re.compile(
    r"\b(talib|ta\.|indicator|macd|rsi|ema|sma|atr|bollinger|kdj|kd\b|dmi|adx|"
    r"cci|obv|williams|stoch|momentum|volatility|ichimoku|sar|ema_cross|ma_cross|"
    r"golden_cross|death_cross|breakout|support|resistance|mavg|moving.?average|"
    r"mean.?reversion|trend|momentum)\b",
    re.IGNORECASE,
)
# Noise / execution-only patterns
NOISE_RE = re.compile(
    r"\b(iceberg|order|buy then sell|ping pong|martingale|fixed investment|"
    r"variable investment|grid|hedge on two contracts|ordersdetail|getminstock|"
    r"python_efaf|python\b.*print|log|final formula)\b",
    re.IGNORECASE,
)

fmz_parser = FMZParser()
catalog = fmz_parser.build_catalog()
lookup = {e.python_identifier: e for e in catalog}

quality = []
noise = []
unknown = []

for name in SIGNAL_STRATEGIES:
    entry = lookup.get(name)
    if not entry:
        unknown.append(name)
        continue
    code = entry.source_code or ""
    desc = entry.description or ""
    has_quality = bool(QUALITY_RE.search(code) or QUALITY_RE.search(desc))
    has_noise = bool(NOISE_RE.search(code) or NOISE_RE.search(desc))
    if has_quality and not has_noise:
        quality.append(name)
    elif has_noise:
        noise.append(name)
    else:
        # Manual fallback: inspect first 300 chars of description/code for clarity
        sample = (desc[:300] + " | " + code[:300]).strip()
        if "Buy" in sample and "Sell" in sample and not has_quality:
            noise.append(name)
        else:
            quality.append(name)

print("=== Quality (indicator/rule-based) strategies ===")
for n in quality:
    print(f"  {n}")
print()
print("=== Noise (execution/utility/no signal logic) strategies ===")
for n in noise:
    print(f"  {n}")
print()
if unknown:
    print("=== Not found ===")
    for n in unknown:
        print(f"  {n}")
