# FMZ Quant Strategy Integration

Alpha Trader now imports the entire [fmzquant/strategies](https://github.com/fmzquant/strategies) repository and exposes its JavaScript/Python strategies as first-class Alpha Trader strategies.

## What was integrated

- **5,807 markdown strategy files** from `fmzquant/strategies` are parsed.
- **493 runnable strategies** (JavaScript/Python source present) are wrapped as `BaseStrategy` subclasses.
- All generated strategies auto-register with `StrategyRegistry` and participate in confluence/execution.

## File map

| File | Purpose |
|------|---------|
| `strategies/fmzquant/` | Git submodule pointing to `github.com/fmzquant/strategies` |
| `strategies/fmz_catalog.json` | Parsed metadata index for all 5,807 files |
| `strategies/fmz_parser.py` | Markdown parser and catalog builder |
| `strategies/fmz_runtime.py` | FMZ `exchange` API adapter + JS/Python sandbox |
| `strategies/generated/batch_*/` | Auto-generated `BaseStrategy` wrappers |
| `scripts/generate_fmz_strategies.py` | Regenerates wrappers from the catalog |
| `tests/test_fmz_integration.py` | Integration tests |

## CLI commands

```bash
# List imported FMZ strategies
python cli.py fmz list
python cli.py fmz list --status ok --limit 20

# Run one strategy against synthetic data
python cli.py fmz run fmz_2014 --symbol SPY --dry-run

# Smoke-test a batch
python cli.py fmz batch --limit 50 --symbol SPY

# Regenerate wrappers after pulling new strategy docs
python cli.py fmz generate
```

## How it works

1. **Parser** reads each markdown file, extracts metadata, argument tables, and source code.
2. **Generator** emits a Python class per runnable strategy that stores the original source and arguments.
3. **Runtime adapter** provides an FMZ-compatible `exchange` object and global helpers:
   - `GetRecords()`, `GetTicker()`, `GetDepth()`, `GetAccount()`, `GetPosition()`, `GetMinStock()`, `Go()`
   - `Buy()` / `Sell()` → captured as Alpha Trader `Signal` objects
   - `Sleep()` / `Log()` / `_C()` / `_D()` / `_G()` / `_N()` / `IsVirtual()` / `_Cross()`
   - `TA.*` helpers backed by pandas: `MA`, `EMA`, `Highest`, `Lowest`, `RSI`, `MACD`, `ATR`, `BOLL`
   - `$.Buy()` / `$.Sell()` / `$.Cross()` wrappers from the FMZ standard library
   - `$.PlotRecords()` / `$.PlotLine()` / `$.PlotFlag()` / `$.PlotHLine()` / `$.PlotVLine()` / `$.GetCfg()` / `$.ChartObj()` chart helpers (output stored, not rendered)
   - `ext` module adapter with explicitly supported helpers
   - `Chart()` object adapter that stores plotted data
   - `talib` compatibility module for both Python and JavaScript strategies, computing real indicators with pandas (`MA`, `EMA`, `SMA`, `RSI`, `MACD`, `ATR`, `BBANDS`, `STOCH`)
   - Exchange-name inference per symbol (`infer_fmz_exchange_name`) so venue-gated strategies see a recognizable FMZ exchange name
4. **Registry** discovers all generated classes alongside native strategies.

### No silent stubs

Unsupported `talib` indicators, unknown `ext.*` methods, and unknown `$.*` helpers raise an exception instead of returning fake values. Charting methods are real output-only adapters: they accept data and return chart objects, but Alpha Trader does not render them because chart output does not generate signals.

## Limitations

- Strategies default to **signal-only** output. Live execution requires the normal Alpha Trader risk/approval flow.
- Strategies run for a bounded number of ticks to avoid infinite `while(true)` loops.
- PineScript-only strategies are cataloged but not executed (no PineScript runtime).
- Strategies that depend on external packages (`web3`, `pymongo`, exchange-specific libs), Python 2 syntax, or unsupported `talib`/`ext`/`$` helpers will fail at runtime and are surfaced in batch smoke tests.
- FMZ argument defaults are extracted from markdown tables; some strategies reference undeclared globals and may need manual argument mapping.
- Signal yield depends on market data: most strategies only fire when their entry conditions are met.

## Regenerating after a submodule update

```bash
git submodule update --remote strategies/fmzquant
source venv/bin/activate
python strategies/fmz_parser.py
python scripts/generate_fmz_strategies.py
python -m pytest tests/test_fmz_integration.py -v
```

## Safety

All generated wrappers set `ExecutionMode.SIGNAL_ONLY` by default. They do not place live orders unless explicitly promoted through Alpha Trader's risk governor and execution router.
