"""
TopstepX / ProjectX API Adapter

For Futures trading (NQ, ES, MES, MNQ, etc.) via the official ProjectX Gateway API.
Requires:
  - PROJECT_X_API_KEY    (from TopstepX Settings → API)
  - PROJECT_X_USERNAME   (TopstepX username)
  - PROJECT_X_ACCOUNT_NAME (optional, to select a specific account)

Safety defaults:
  - TOPSTEP_TRADING_ENABLED=false   # Must be explicitly set to "true" to send orders.
  - TOPSTEP_DRY_RUN=false           # If true, orders are logged but not sent.
  - TOPSTEP_ORDER_CONFIRMATION=true # If true, place_order requires confirmed=True.
  - TOPSTEP_MAX_CONTRACTS=5
  - TOPSTEP_MAX_DAILY_LOSS=1000

Uses project-x-py SDK.
"""

import asyncio
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

try:
    from project_x_py import ProjectX, OrderSide, OrderType
    from project_x_py.order_manager import OrderManager
    from project_x_py.event_bus import EventBus
    TOPSTEP_AVAILABLE = True
except ImportError:
    TOPSTEP_AVAILABLE = False
    logger.warning("project-x-py not installed. TopstepX integration disabled.")
    ProjectX = None  # type: ignore
    OrderSide = None  # type: ignore
    OrderType = None  # type: ignore
    OrderManager = None  # type: ignore
    EventBus = None  # type: ignore

try:
    import jwt
except ImportError:
    jwt = None


class TopstepSafetyError(Exception):
    """Raised when a safety guardrail blocks an order."""


class TopstepClient:
    """TopstepX API client via ProjectX Gateway."""

    def __init__(self):
        self.api_key = os.getenv("PROJECT_X_API_KEY") or os.getenv("TOPSTEP_API_KEY")
        self.username = os.getenv("PROJECT_X_USERNAME") or os.getenv("TOPSTEP_USERNAME")
        self.account_name = os.getenv("PROJECT_X_ACCOUNT_NAME")

        self.max_daily_loss = float(os.getenv("TOPSTEP_MAX_DAILY_LOSS", 1000.0))
        self.max_contracts = int(os.getenv("TOPSTEP_MAX_CONTRACTS", 5))
        self.starting_balance = float(os.getenv("TOPSTEP_STARTING_BALANCE", 50000.0))
        self.trading_enabled = os.getenv("TOPSTEP_TRADING_ENABLED", "false").lower() == "true"
        self.dry_run = os.getenv("TOPSTEP_DRY_RUN", "false").lower() == "true"
        self.require_confirmation = os.getenv("TOPSTEP_ORDER_CONFIRMATION", "true").lower() == "true"

        self._client: Optional[Any] = None
        self._authenticated = False
        self._account: Optional[Any] = None
        self._order_manager: Optional[Any] = None
        self._instrument_cache: Dict[str, Any] = {}
        self._oco_tasks: set = set()

    # ------------------------------------------------------------------
    # Safety / guardrails
    # ------------------------------------------------------------------
    def _check_trading_enabled(self) -> None:
        if not self.trading_enabled:
            raise TopstepSafetyError(
                "TopstepX order placement is DISABLED. "
                "Set TOPSTEP_TRADING_ENABLED=true in .env to enable live orders."
            )

    def _check_confirmation(self, confirmed: bool) -> None:
        if self.require_confirmation and not confirmed:
            raise TopstepSafetyError(
                "Order confirmation required. Pass confirmed=True to execute."
            )

    @staticmethod
    def _normalize_side(side: str) -> OrderSide:
        s = side.upper().strip()
        if s in ("BUY", "LONG"):
            return OrderSide.BUY
        if s in ("SELL", "SHORT"):
            return OrderSide.SELL
        raise TopstepSafetyError(f"Invalid side '{side}'. Use buy/sell/long/short.")

    async def _current_exposure_for_symbol(self, symbol: str) -> Dict:
        """Return current open position for the given simple symbol."""
        contract_id = await self._get_contract_id(symbol)
        if not contract_id:
            return {"side": None, "size": 0}
        positions = await self.get_positions()
        for pos in positions:
            if pos.get("contract_id") == contract_id:
                return {"side": pos.get("side"), "size": pos.get("size", 0)}
        return {"side": None, "size": 0}

    def _check_position_sizing(
        self,
        symbol: str,
        side: str,
        quantity: int,
        current: Dict,
    ) -> int:
        """Enforce max-contracts and prevent accidental reversal/add-on."""
        current_size = current.get("size", 0) or 0
        current_side = current.get("side")
        new_side = "long" if side.upper() in ("BUY", "LONG") else "short"

        if current_size > 0 and current_side and current_side != new_side:
            raise TopstepSafetyError(
                f"Existing {current_side} position of {current_size} {symbol} already open. "
                "Flatten first or pass allow_position_override=True."
            )

        total_size = current_size + quantity
        if total_size > self.max_contracts:
            raise TopstepSafetyError(
                f"Order would exceed max contracts: current={current_size}, "
                f"requested={quantity}, max={self.max_contracts}."
            )
        return total_size

    # ------------------------------------------------------------------
    # Client lifecycle
    # ------------------------------------------------------------------
    def _client_ready(self) -> bool:
        if not TOPSTEP_AVAILABLE:
            return False
        if not self.api_key or not self.username:
            logger.warning("PROJECT_X_API_KEY and PROJECT_X_USERNAME not configured")
            return False
        return True

    async def _ensure_client(self) -> Optional[Any]:
        if not self._client_ready():
            return None
        if self._client is None:
            try:
                self._client = ProjectX(
                    username=self.username,
                    api_key=self.api_key,
                    account_name=self.account_name,
                )
            except Exception as e:
                logger.error(f"Failed to create ProjectX client: {e}")
                return None
        if not self._authenticated:
            try:
                await self._client.authenticate()
                self._authenticated = True
                logger.info("TopstepX / ProjectX client authenticated")
            except Exception as e:
                logger.error(f"ProjectX authentication failed: {e}")
                return None
        return self._client

    async def _get_account(self):
        client = await self._ensure_client()
        if not client:
            return None
        if self._account is None:
            try:
                if self.account_name:
                    accounts = await client.list_accounts()
                    for acc in accounts:
                        if acc.name == self.account_name:
                            self._account = acc
                            break
                    if self._account is None:
                        logger.warning(f"Account '{self.account_name}' not found; using default")
                if self._account is None:
                    self._account = client.get_account_info()
            except Exception as e:
                logger.error(f"Failed to get TopstepX account: {e}")
                return None
        return self._account

    async def _get_order_manager(self) -> Optional[Any]:
        client = await self._ensure_client()
        if not client:
            return None
        if self._order_manager is None:
            self._order_manager = OrderManager(project_x_client=client, event_bus=EventBus())
        return self._order_manager

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------
    async def _fetch_positions_raw(self, client) -> List[Dict]:
        """Fetch raw positions from TopstepX user API (bypasses SDK model mismatch)."""
        if jwt is None:
            return []
        try:
            token = client.session_token
            payload = jwt.decode(token, options={"verify_signature": False})
            user_id = payload.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier")
            if not user_id:
                return []
            resp = await client._client.get(
                f"https://userapi.topstepx.com/Position/all/user/{user_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"TopstepX raw positions fetch error: {e}")
            return []

    async def get_positions(self) -> List[Dict]:
        """Get open futures positions."""
        client = await self._ensure_client()
        if not client:
            return []

        try:
            positions = await self._fetch_positions_raw(client)
            result = []
            for pos in positions:
                size = int(pos.get("positionSize", 0))
                if size == 0:
                    continue
                result.append({
                    "venue": "TopstepX",
                    "symbol": pos.get("contractId"),
                    "contract_id": pos.get("contractId"),
                    "side": "long" if size > 0 else "short",
                    "size": abs(size),
                    "entry": float(pos.get("averagePrice", 0)),
                    "account_id": pos.get("accountId"),
                })
            return result
        except Exception as e:
            logger.error(f"Topstep positions error: {e}")
            return []

    # ------------------------------------------------------------------
    # Compliance
    # ------------------------------------------------------------------
    async def check_combine_compliance(self) -> Dict:
        """Basic Combine compliance check using account balance and positions."""
        account = await self._get_account()
        if account is None:
            return {"status": "error", "reason": "Not connected"}

        try:
            positions = await self._fetch_positions_raw(self._client)
            open_contracts = sum(abs(int(p.get("positionSize", 0))) for p in positions)
            balance = float(account.balance)

            is_compliant = True
            reasons = []

            if balance <= 0:
                is_compliant = False
                reasons.append(f"Account balance is ${balance:.2f}")

            if open_contracts >= self.max_contracts:
                is_compliant = False
                reasons.append(f"At or above max contracts: {open_contracts}/{self.max_contracts}")

            daily_loss_used = self.starting_balance - balance
            if daily_loss_used >= self.max_daily_loss:
                is_compliant = False
                reasons.append(
                    f"Daily loss limit reached: ${daily_loss_used:.2f} / ${self.max_daily_loss:.2f}"
                )

            return {
                "compliant": is_compliant,
                "reasons": reasons,
                "balance": balance,
                "open_contracts": open_contracts,
                "max_contracts": self.max_contracts,
                "starting_balance": self.starting_balance,
                "daily_loss_used": self.starting_balance - balance,
                "max_daily_loss": self.max_daily_loss,
                "account_name": account.name,
                "can_trade": account.canTrade,
            }
        except Exception as e:
            logger.error(f"Topstep compliance check error: {e}")
            return {"status": "error", "reason": str(e)}

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------
    async def _get_contract_id(self, symbol: str) -> Optional[str]:
        symbol = symbol.upper()
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol].id
        client = await self._ensure_client()
        if not client:
            return None
        try:
            instrument = await client.get_instrument(symbol, live=False)
            self._instrument_cache[symbol] = instrument
            return instrument.id
        except Exception as e:
            logger.error(f"Failed to resolve contract for {symbol}: {e}")
            return None

    async def get_bars(
        self,
        symbol: str,
        days: int = 1,
        interval: int = 5,
        unit: int = 2,
    ) -> List[Dict]:
        """Fetch intraday futures bars from the TopstepX / ProjectX Gateway."""
        client = await self._ensure_client()
        if not client:
            return []

        contract_id = await self._get_contract_id(symbol)
        if not contract_id:
            return []

        try:
            bars = await client.get_bars(symbol, days=days, interval=interval, unit=unit, partial=True)
            if bars.is_empty():
                return []

            result = []
            for row in bars.to_dicts():
                ts = row.get("timestamp") or row.get("date") or row.get("time")
                if hasattr(ts, "isoformat"):
                    ts = ts.isoformat()
                result.append({
                    "timestamp": ts or datetime.utcnow().isoformat(),
                    "open": float(row.get("open", 0)),
                    "high": float(row.get("high", 0)),
                    "low": float(row.get("low", 0)),
                    "close": float(row.get("close", 0)),
                    "volume": int(row.get("volume", 0) or 0),
                })
            return result
        except Exception as e:
            logger.error(f"Topstep bars error for {symbol}: {e}")
            return []

    async def get_price(self, symbol: str) -> Dict:
        """Get latest price for a futures symbol."""
        client = await self._ensure_client()
        if not client:
            return {"error": "Not connected"}

        try:
            contract_id = await self._get_contract_id(symbol)
            if not contract_id:
                return {"error": f"Could not resolve contract for {symbol}"}

            bars = await client.get_bars(symbol, days=1, interval=5, unit=2, partial=True)
            if bars.is_empty():
                return {"error": "No price data available"}

            last = bars.tail(1).to_dicts()[0]
            return {
                "symbol": symbol,
                "contract_id": contract_id,
                "last": float(last.get("close", 0)),
                "bid": float(last.get("bid", 0) or last.get("close", 0)),
                "ask": float(last.get("ask", 0) or last.get("close", 0)),
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"Topstep price error for {symbol}: {e}")
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    async def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str = "MARKET",
        price: Optional[float] = None,
        confirmed: bool = False,
        allow_position_override: bool = False,
    ) -> Dict:
        """Place a futures order with Combine guardrails.

        Args:
            symbol: Futures symbol (NQ, ES, MNQ, MES, etc.)
            quantity: Number of contracts.
            side: buy/sell/long/short.
            order_type: MARKET or LIMIT.
            price: Required for LIMIT orders.
            confirmed: Required when TOPSTEP_ORDER_CONFIRMATION=true.
            allow_position_override: Bypass reversal/add-on block (use with care).
        """
        # 0. Safety gates
        try:
            self._check_trading_enabled()
            self._check_confirmation(confirmed)
        except TopstepSafetyError as e:
            logger.error(f"TopstepX safety block: {e}")
            return {"status": "blocked", "error": str(e)}

        client = await self._ensure_client()
        if not client:
            return {"status": "failed", "error": "Not connected"}

        # 1. Compliance Check
        compliance = await self.check_combine_compliance()
        if not compliance.get("compliant", False):
            logger.error(f"🚨 COMBINE RULE VIOLATION PREVENTED: {compliance.get('reasons')}")
            return {"status": "failed", "reason": "Combine Rule Restriction"}

        # 2. Resolve contract
        contract_id = await self._get_contract_id(symbol)
        if not contract_id:
            return {"status": "failed", "error": f"Could not resolve contract for {symbol}"}

        # 3. Position sizing / reversal guard
        current = await self._current_exposure_for_symbol(symbol)
        try:
            if not allow_position_override:
                self._check_position_sizing(symbol, side, quantity, current)
        except TopstepSafetyError as e:
            logger.error(f"TopstepX sizing block: {e}")
            return {"status": "blocked", "error": str(e)}

        # 4. Dry run
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would place {side.upper()} {quantity} {symbol} "
                f"({order_type}) at ~{price}"
            )
            return {
                "status": "simulated",
                "symbol": symbol,
                "contract_id": contract_id,
                "quantity": quantity,
                "side": side.upper(),
                "order_type": order_type.upper(),
                "venue": "TopstepX",
            }

        # 5. Map side and order type
        side_enum = self._normalize_side(side)
        order_type_upper = order_type.upper()

        try:
            om = await self._get_order_manager()
            if om is None:
                return {"status": "failed", "error": "Order manager not available"}

            if order_type_upper == "MARKET":
                resp = await om.place_market_order(
                    contract_id=contract_id, side=side_enum.value, size=quantity
                )
            elif order_type_upper == "LIMIT":
                if price is None:
                    return {"status": "failed", "error": "Limit order requires price"}
                resp = await om.place_limit_order(
                    contract_id=contract_id,
                    side=side_enum.value,
                    size=quantity,
                    limit_price=price,
                )
            else:
                return {"status": "failed", "error": f"Unsupported order type: {order_type}"}

            if resp.success:
                logger.info(
                    f"TopstepX order submitted: {side.upper()} {quantity} {symbol} "
                    f"@ {order_type_upper}, id={resp.orderId}"
                )
                return {
                    "status": "submitted",
                    "order_id": str(resp.orderId),
                    "symbol": symbol,
                    "contract_id": contract_id,
                    "quantity": quantity,
                    "side": side.upper(),
                    "order_type": order_type_upper,
                    "venue": "TopstepX",
                    "executed_at": datetime.utcnow().isoformat(),
                }
            else:
                return {
                    "status": "failed",
                    "error": resp.errorMessage or f"Order rejected (code {resp.errorCode})",
                }
        except Exception as e:
            logger.error(f"Topstep order error: {e}")
            return {"status": "failed", "error": str(e)}

    # ------------------------------------------------------------------
    # Bracket / OCO execution (polling-based, no live event bus required)
    # ------------------------------------------------------------------
    async def _wait_for_order_fill(
        self,
        order_id: int,
        timeout_seconds: int = 60,
        poll_interval: float = 1.0,
    ) -> Optional[Dict]:
        """Poll raw order endpoint until order is filled or timeout."""
        client = await self._ensure_client()
        if not client:
            return None
        account = await self._get_account()
        account_id = account.id if account else None
        token = client.session_token
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        url = f"https://userapi.topstepx.com/Order?accountId={account_id}"
        headers = {"Authorization": f"Bearer {token}"}
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client._client.get(url, headers=headers)
                resp.raise_for_status()
                for o in resp.json():
                    if o.get("id") == order_id:
                        if o.get("status") == 2 and o.get("totalFilled", 0) > 0:
                            return o
                        if o.get("status") in (3, 4):  # cancelled / rejected
                            return o
            except Exception as e:
                logger.warning(f"Order poll error for {order_id}: {e}")
            await asyncio.sleep(poll_interval)
        return None

    async def _cancel_order_by_id(self, order_id: int) -> bool:
        """Cancel an order via the SDK."""
        try:
            om = await self._get_order_manager()
            if om is None:
                return False
            return await om.cancel_order(order_id, account_id=self._account.id if self._account else None)
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    @staticmethod
    def _is_order_open(status: Optional[Dict]) -> bool:
        """Return True if the order is still working/open (status == 1)."""
        if not status:
            return False
        return status.get("status") == 1

    async def _get_order_status(self, order_id: Optional[int]) -> Optional[Dict]:
        """Fetch a single order's status from the TopstepX user API."""
        if order_id is None:
            return None
        client = await self._ensure_client()
        if not client:
            return None
        account = await self._get_account()
        account_id = account.id if account else None
        token = client.session_token
        url = f"https://userapi.topstepx.com/Order?accountId={account_id}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = await client._client.get(url, headers=headers)
            resp.raise_for_status()
            for o in resp.json():
                if o.get("id") == order_id:
                    return o
        except Exception as e:
            logger.warning(f"Order status fetch error for {order_id}: {e}")
        return None

    async def _oco_monitor(
        self,
        contract_id: str,
        stop_order_id: Optional[int],
        target_order_id: Optional[int],
    ) -> None:
        """Background task: cancel the surviving protective order once position is flat.

        Monitors indefinitely (up to TOPSTEP_OCO_MAX_MINUTES, default 8 hours) by
        polling order status directly so a surviving stop/target is never left behind.
        """
        max_minutes = float(os.getenv("TOPSTEP_OCO_MAX_MINUTES", 480))
        deadline = asyncio.get_event_loop().time() + (max_minutes * 60)
        try:
            while True:
                now = asyncio.get_event_loop().time()
                if now >= deadline:
                    logger.warning("OCO monitor: max duration reached, cancelling any surviving orders")
                    stop_status = await self._get_order_status(stop_order_id)
                    target_status = await self._get_order_status(target_order_id)
                    if self._is_order_open(stop_status):
                        await self._cancel_order_by_id(stop_order_id)
                    if self._is_order_open(target_status):
                        await self._cancel_order_by_id(target_order_id)
                    return

                positions = await self.get_positions()
                flat = all(p.get("contract_id") != contract_id for p in positions)
                stop_status = await self._get_order_status(stop_order_id)
                target_status = await self._get_order_status(target_order_id)
                stop_open = self._is_order_open(stop_status)
                target_open = self._is_order_open(target_status)

                if flat:
                    logger.info("OCO monitor: position flat, cancelling surviving orders")
                    if stop_open:
                        await self._cancel_order_by_id(stop_order_id)
                    if target_open:
                        await self._cancel_order_by_id(target_order_id)
                    return

                if not stop_open and not target_open:
                    logger.info("OCO monitor: both protective orders closed")
                    return

                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("OCO monitor cancelled, cleaning up protective orders")
            if stop_order_id:
                await self._cancel_order_by_id(stop_order_id)
            if target_order_id:
                await self._cancel_order_by_id(target_order_id)
            raise
        except Exception as e:
            logger.error(f"OCO monitor error: {e}")

    async def place_bracket_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        stop_loss: float,
        take_profit: float,
        entry_price: Optional[float] = None,
        order_type: str = "MARKET",
        confirmed: bool = False,
    ) -> Dict:
        """Place entry + stop + target with an OCO monitor.

        This implementation does NOT rely on the SDK's broken bracket handler.
        It polls for the entry fill, then places protective orders, then starts
        a background monitor to cancel the surviving order once the position closes.
        """
        try:
            self._check_trading_enabled()
            self._check_confirmation(confirmed)
        except TopstepSafetyError as e:
            return {"status": "blocked", "error": str(e)}

        contract_id = await self._get_contract_id(symbol)
        if not contract_id:
            return {"status": "failed", "error": f"Could not resolve contract for {symbol}"}

        current = await self._current_exposure_for_symbol(symbol)
        try:
            self._check_position_sizing(symbol, side, quantity, current)
        except TopstepSafetyError as e:
            return {"status": "blocked", "error": str(e)}

        if self.dry_run:
            return {
                "status": "simulated",
                "symbol": symbol,
                "quantity": quantity,
                "side": side.upper(),
                "entry_type": order_type.upper(),
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }

        side_enum = self._normalize_side(side)
        protective_side = OrderSide.SELL.value if side_enum == OrderSide.BUY else OrderSide.BUY.value

        # 1. Place entry order
        entry_resp = await self.place_order(
            symbol=symbol,
            quantity=quantity,
            side=side,
            order_type=order_type,
            price=entry_price,
            confirmed=True,  # already gated above
        )
        if entry_resp.get("status") != "submitted":
            return {"status": "failed", "error": f"Entry failed: {entry_resp}", "entry": entry_resp}

        entry_order_id = int(entry_resp["order_id"])

        # 2. Wait for fill
        filled = await self._wait_for_order_fill(entry_order_id, timeout_seconds=60)
        if not filled or filled.get("status") != 2:
            logger.error(f"Bracket entry {entry_order_id} did not fill; cancelling")
            await self._cancel_order_by_id(entry_order_id)
            return {"status": "failed", "error": "Entry order did not fill", "entry_order_id": entry_order_id}

        # 3. Place protective orders
        om = await self._get_order_manager()
        if om is None:
            return {"status": "failed", "error": "Order manager unavailable after entry"}

        stop_resp = await om.place_stop_order(
            contract_id=contract_id,
            side=protective_side,
            size=quantity,
            stop_price=stop_loss,
            account_id=self._account.id if self._account else None,
        )
        target_resp = await om.place_limit_order(
            contract_id=contract_id,
            side=protective_side,
            size=quantity,
            limit_price=take_profit,
            account_id=self._account.id if self._account else None,
        )

        # 4. Start OCO monitor
        task = asyncio.create_task(
            self._oco_monitor(
                contract_id,
                stop_resp.orderId if stop_resp and stop_resp.success else None,
                target_resp.orderId if target_resp and target_resp.success else None,
            )
        )
        self._oco_tasks.add(task)
        task.add_done_callback(self._oco_tasks.discard)

        return {
            "status": "submitted",
            "symbol": symbol,
            "contract_id": contract_id,
            "quantity": quantity,
            "side": side.upper(),
            "entry_order_id": entry_order_id,
            "stop_order_id": stop_resp.orderId if stop_resp and stop_resp.success else None,
            "target_order_id": target_resp.orderId if target_resp and target_resp.success else None,
            "venue": "TopstepX",
        }

    async def flatten_all(self, confirmed: bool = False) -> List[Dict]:
        """Market-close all open TopstepX futures positions."""
        try:
            self._check_trading_enabled()
            self._check_confirmation(confirmed)
        except TopstepSafetyError as e:
            return [{"status": "blocked", "error": str(e)}]

        results = []
        positions = await self.get_positions()
        for pos in positions:
            symbol = pos.get("symbol", "").split(".")[-2] if "." in pos.get("symbol", "") else pos.get("symbol")
            # Try to map contract_id back to simple symbol
            # Fallback: pass the contract_id directly if lookup fails
            side = "sell" if pos.get("side") == "long" else "buy"
            qty = pos.get("size", 0)
            if qty <= 0:
                continue
            # Use contract_id as symbol for place_order if simple symbol unknown
            res = await self.place_order(symbol=symbol or pos.get("contract_id"), quantity=qty, side=side, confirmed=True)
            results.append(res)
        return results

    async def close(self):
        """Cancel any running OCO monitors."""
        for task in list(self._oco_tasks):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# Singleton instance
_topstep_client = None


def get_topstep_client() -> TopstepClient:
    global _topstep_client
    if _topstep_client is None:
        _topstep_client = TopstepClient()
    return _topstep_client


async def topstep_get_price(symbol: str) -> Dict:
    return await get_topstep_client().get_price(symbol)


async def topstep_get_bars(symbol: str, days: int = 1, interval: int = 5) -> List[Dict]:
    return await get_topstep_client().get_bars(symbol, days=days, interval=interval)


async def topstep_place_order(**kwargs) -> Dict:
    return await get_topstep_client().place_order(**kwargs)


async def topstep_get_positions() -> List[Dict]:
    return await get_topstep_client().get_positions()


async def topstep_check_compliance() -> Dict:
    return await get_topstep_client().check_combine_compliance()


async def topstep_place_bracket_order(**kwargs) -> Dict:
    return await get_topstep_client().place_bracket_order(**kwargs)


async def topstep_flatten_all(**kwargs) -> List[Dict]:
    return await get_topstep_client().flatten_all(**kwargs)
