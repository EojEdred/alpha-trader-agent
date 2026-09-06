"""Inspect source of the indicator strategies that error in quality smoke test."""
import re
from strategies.fmz_parser import FMZParser

NAMES = [
    "fmz_keltner_10_v23_dev",
    "fmz_macd_c63f",
    "fmz_python_8561",
    "fmz_bollmaboll",
    "fmz_rsi_9020",
]

fmz_parser = FMZParser()
catalog = fmz_parser.build_catalog()
lookup = {e.python_identifier: e for e in catalog}

for name in NAMES:
    e = lookup.get(name)
    if not e:
        print(f"\n{name}: NOT FOUND")
        continue
    print(f"\n{'='*70}\n{name} ({e.source_language})\n{e.name}\nDescription: {e.description[:300]}")
    print("-"*70)
    print(e.source_code)
