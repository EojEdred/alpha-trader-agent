# Alpha Trader — Agent Handoff

**Date:** 2026-09-03  
**Project:** `/Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent`  
**Current mode:** Production-readiness push for broker connectivity + new venue adapters.

---

## What is already done

### Signal engine
- Added a second regime-aware signal source (`regime_aware_breakout_signal`) in `scripts/regime_overlay.py`.
- Wired breakout + pullback signals into `scripts/live_intents.py` and `scripts/backtest_focus.py`.
- Latest combined backtest (90-day, excluding GC because Yahoo hangs): **22 trades, 54.5% win rate, PF 1.75**.
- Live dry-run pipeline is functional and writes approved intents to `data/paper_trades.csv`.

### Market data
- Added the user's Massive API key to `.env` as `MASSIVE_API_KEY`.
- `market_data/providers/massive_provider.py` is active for previous-close prices on equities.
- Yahoo Finance remains the fallback for historical candles and forex futures.

### OANDA
- Adapter at `tools/oanda.py` is connected to the live account.
- Current balance/NAV: **$16.7390**.
- Added 4 forex pairs to the live signal pipeline in `scripts/live_intents.py`: `EURUSD`, `USDJPY`, `GBPUSD`, `AUDUSD`.
- Verified margin rates on the account: EUR/USD 2%, AUD/USD 3%, GBP/USD 5%, USD/JPY 5%.
- **Important:** this account lists 68 forex pairs and has **no XAU/USD**. Gold must route through Topstep (GC futures) or Schwab (GLD) unless metals are enabled/funded later.

### TopstepX
- Installed a local Python 3.12 interpreter at `.python/cpython-3.12.13-macos-aarch64-none`.
- Created `.venv-topstep` and installed `project-x-py==3.5.9`.
- The legacy `tools/topstep.py` still expects the SDK to be importable in the main 3.11 venv, so it is currently disabled (`TOPSTEP_AVAILABLE=False`).
- SDK auth test failed with the current credentials because they are web-login credentials, not ProjectX Gateway credentials.

### Kalshi
- Replaced old v1 email/password stub with a proper v2 API-key adapter in `tools/kalshi.py`.
- Uses `KALSHI_API_KEY` env var.

### Polymarket
- Replaced broken ccxt stub with official `py_clob_client` wrapper in `tools/polymarket.py`.
- Requires `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`.

### Crypto
- Added new `tools/ccxt_client.py` adapter using CCXT.
- Requires `CRYPTO_EXCHANGE`, `CRYPTO_API_KEY`, `CRYPTO_API_SECRET`, and optionally `CRYPTO_API_PASSPHRASE`.

### Env / git
- Updated `.env.example` with all new required variables.
- Added `.python/` and `tmp_topstep_sdk/` to `.gitignore`.

### User-facing checklist
- Generated a styled HTML/PDF checklist on the Desktop:
  - `/Users/joe/Desktop/AlphaTrader_Account_Checklist.html`
  - `/Users/joe/Desktop/AlphaTrader_Account_Checklist.pdf`

---

## What needs to be done next

These are the active blockers. The user is aware of all of them and said they will provide the missing pieces.

### 1. Schwab OAuth re-authentication
**Status:** waiting on user.  
**Action:** The user needs to click the Schwab OAuth URL and paste the final redirect URL. Then run:

```bash
cd /Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent
source venv/bin/activate
python scripts/schwab_auth.py '<redirect_url>'
```

Then verify with a quick account-number fetch.

### 2. OANDA funding
**Status:** waiting on user.  
**Action:** User should deposit ~$500+ (recommended $1,000) and confirm whether metals/XAU are enabled. If XAU/USD is not enabled, gold signals should route through Topstep/Schwab instead.

### 3. TopstepX ProjectX credentials
**Status:** waiting on user.  
**Action:** User needs to add to `.env`:

```env
PROJECT_X_API_KEY=
PROJECT_X_USERNAME=
PROJECT_X_ACCOUNT_NAME=
```

These come from TopstepX → Settings → API Keys, not the web login. After they are set, re-test with:

```bash
.venv-topstep/bin/python - <<'PY'
import asyncio, os
from dotenv import load_dotenv
load_dotenv(dotenv_path='.env')
from project_x_py import ProjectX
async def main():
    async with ProjectX(
        username=os.getenv('PROJECT_X_USERNAME'),
        api_key=os.getenv('PROJECT_X_API_KEY'),
        account_name=os.getenv('PROJECT_X_ACCOUNT_NAME'),
    ) as client:
        await client.authenticate()
        print(client.get_account_info())
asyncio.run(main())
PY
```

Once auth works, decide how to bridge the 3.12 SDK into the main 3.11 app. Options:
- Run a small JSON-RPC/HTTP bridge process inside `.venv-topstep` and have `tools/topstep.py` talk to it.
- Port the needed endpoints to direct REST calls in the main venv (more work, no Python 3.12 dependency).

### 4. Kalshi API key
**Status:** waiting on user.  
**Action:** Add `KALSHI_API_KEY` to `.env`. Then run a connectivity test via `tools/kalshi.py`.

### 5. Polymarket credentials
**Status:** waiting on user.  
**Action:** Add `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE` to `.env`. Then test `tools/polymarket.py`.

### 6. Crypto exchange credentials
**Status:** waiting on user.  
**Action:** Add `CRYPTO_EXCHANGE`, `CRYPTO_API_KEY`, `CRYPTO_API_SECRET`, and `CRYPTO_API_PASSPHRASE` (if required) to `.env`. Then test `tools/ccxt_client.py`.

---

## Useful commands for the next agent

```bash
# Run the live signal pipeline in dry-run mode
source venv/bin/activate
python scripts/live_intents.py --simulate-execution

# Test OANDA connectivity
python -c "import asyncio; from tools.oanda import get_oanda_client; async def m(): print(await get_oanda_client().get_account()); asyncio.run(m())"

# Test Kalshi (after key is set)
python -c "import asyncio; from tools.kalshi import get_kalshi_client; async def m(): print(await get_kalshi_client().get_exchange_status()); asyncio.run(m())"

# Test Polymarket read-only (no creds needed)
python -c "import asyncio; from tools.polymarket import get_polymarket_client; async def m(): print(await get_polymarket_client().get_ok()); asyncio.run(m())"

# Test crypto read-only (no creds needed)
python -c "import asyncio; from tools.ccxt_client import get_crypto_client; async def m(): print(await get_crypto_client().get_ticker('BTC/USD')); asyncio.run(m())"
```

---

## Notes

- Do **not** commit `.env`, `schwab_token.json`, `.venv-topstep`, or `.python/`.
- The latest dry-run output is in `data/paper_trades.csv`.
- The Desktop checklist PDF is the best single reference to hand back to the user.
