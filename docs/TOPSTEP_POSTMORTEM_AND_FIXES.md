# TopstepX / ProjectX Post-Mortem & Safety Fixes

## Incident

On 2026-06-26 a manual NQ futures trade was attempted through `tools/topstep.py`.
The result was a loss of approximately **$1,451** on a $50K TopstepX combine,
leaving the account **$548 away from the $2,000 max-loss rule**.

### Sequence of events

1. Tried to place a **Long 2 NQ** bracket order (entry + stop + target).
2. The SDK's `place_bracket_order` failed because it requires a live WebSocket
   event bus to detect fills; our `OrderManager` was created with a dummy `EventBus`.
3. The failed bracket left an **unintended 4-contract long position** instead of 2.
4. After reducing size back to 2 and adding a manual stop/target, the stop was
   hit quickly at 29,269 (slippage from 29,270).
5. The leftover take-profit order was cancelled once the flat position was detected.

## Root causes

| Issue | Why it mattered |
|-------|-----------------|
| No master kill switch | Orders could fire without an explicit enable flag. |
| No confirmation gate | `place_order` did not require explicit user confirmation. |
| No position-sizing/reversal guard | The wrapper allowed adding to / reversing an existing position without checks. |
| Broken SDK bracket handling | `OrderManager` was created without a real event bus, so `_wait_for_order_fill` crashed. |
| Side mapping only accepted `buy`/`sell` | Callers passing `long`/`short` (e.g., `tools/execution.py`) would be mapped to `SELL`. |
| Inadequate testing | Only a simple market-in/market-out test was run before risking real combine capital. |

## Fixes applied to `tools/topstep.py`

1. **Hard kill switch**
   - `TOPSTEP_TRADING_ENABLED=false` in `.env`.
   - All order functions return `blocked` until explicitly set to `true`.

2. **Explicit confirmation**
   - `TOPSTEP_ORDER_CONFIRMATION=true` by default.
   - Every order requires `confirmed=True`.

3. **Dry-run mode**
   - `TOPSTEP_DRY_RUN=true` logs the order without sending it.

4. **Position guardrails**
   - Existing position blocks an opposite-side order unless `allow_position_override=True`.
   - Total size cannot exceed `TOPSTEP_MAX_CONTRACTS` (set to **2** for now).

5. **Side mapping**
   - Accepts `buy`/`sell` **and** `long`/`short`.

6. **Polling-based bracket / OCO**
   - New `place_bracket_order` does **not** use the SDK's broken bracket handler.
   - It places entry, polls the raw order endpoint for fill, then places stop + target.
   - A background `OCO` monitor cancels the surviving protective order once the position is flat.

7. **Flatten helper**
   - `flatten_all()` closes all open futures positions.

8. **Unit tests**
   - `tests/test_topstep.py` verifies the guardrails without touching a live account.

## Current `.env` safety settings

```env
TOPSTEP_TRADING_ENABLED=false
TOPSTEP_ORDER_CONFIRMATION=true
TOPSTEP_DRY_RUN=false
TOPSTEP_MAX_CONTRACTS=2
TOPSTEP_MAX_DAILY_LOSS=500
```

## Operational rule going forward

1. No TopstepX order can be placed unless `TOPSTEP_TRADING_ENABLED=true` is set in `.env`.
2. Any code path that calls `topstep_place_order` or `topstep_place_bracket_order` must pass `confirmed=True`.
3. Test new execution logic with `TOPSTEP_DRY_RUN=true` first.
4. Keep size small until the combine is rebuilt (max 2 contracts).

## Known limitations

- The OCO monitor polls every 5 seconds for up to 30 minutes. If the protective orders are not filled within 30 minutes and the position is still open, the surviving order may remain active and require manual cancellation.
- `place_bracket_order` uses market entry by default; limit-entry bracket orders are supported but still need the entry to fill within the poll timeout.
- The `OrderManager` still uses a local `EventBus` instance. It is sufficient for simple order placement but not for true real-time streaming.
