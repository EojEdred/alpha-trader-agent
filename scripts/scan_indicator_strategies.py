"""Scan the FMZ catalog for strategies that appear to use real indicators."""
import re
from strategies.fmz_parser import FMZParser

INDICATOR_RE = re.compile(
    r"\b(TA\.|talib|TA-Lib|Indicator|MACD|RSI|EMA|SMA|WMA|ATR|Bollinger|BOLL|"
    r"KDJ|KD\b|DMI|ADX|CCI|OBV|Williams|WPR|Stoch|STOCH|Momentum|MFI|"
    r"Ichimoku|SAR|Parabolic|EMA[_ ]cross|MA[_ ]cross|golden[_ ]cross|death[_ ]cross|"
    r"breakout|support|resistance|mavg|moving.?average|mean.?reversion|"
    r"trend|momentum|volatility|stddev|StdDev)\b",
    re.IGNORECASE,
)

# Patterns that are execution-only / noise even if they mention an indicator word.
NOISE_RE = re.compile(
    r"\b(iceberg|order|buy then sell|ping pong|martingale|fixed investment|"
    r"variable investment|grid|hedge on two contracts|ordersdetail|getminstock|"
    r"模板库使用例子|封装|定投|插件|下单|委托)\b",
    re.IGNORECASE,
)

fmz_parser = FMZParser()
catalog = fmz_parser.build_catalog()
real = [e for e in catalog if e.parse_status == "ok"]

indicator_strategies = []
noise_strategies = []
other_strategies = []
for e in real:
    text = (e.source_code or "") + "\n" + (e.description or "")
    has_ind = bool(INDICATOR_RE.search(text))
    has_noise = bool(NOISE_RE.search(text))
    if has_ind and not has_noise:
        indicator_strategies.append(e)
    elif has_noise:
        noise_strategies.append(e)
    else:
        other_strategies.append(e)

print(f"Total real strategies: {len(real)}")
print(f"Indicator-based (quality): {len(indicator_strategies)}")
print(f"Noise/execution-only: {len(noise_strategies)}")
print(f"Other: {len(other_strategies)}")
print()
print("=== Indicator-based strategies ===")
for e in indicator_strategies:
    hits = sorted(set(INDICATOR_RE.findall(e.source_code + "\n" + e.description)))
    print(f"  {e.python_identifier}: {e.name} [{e.source_language}] hits={hits}")
