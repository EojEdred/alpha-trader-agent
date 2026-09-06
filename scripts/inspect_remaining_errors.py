"""Inspect the remaining error strategies after runtime fixes."""
from strategies.fmz_parser import FMZParser

NAMES = [
    "fmz_keltner_10_v23_dev",
    "fmz_strategy_86e0",
    "fmz_v02",
    "fmz_strategy_37de",
    "fmz_strategy_af2c",
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
