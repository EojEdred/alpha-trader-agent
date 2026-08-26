"""
Tradovate API Adapter

For Apex (and other) funded futures accounts that trade through Tradovate.
Supports account info, positions, orders, P&L, and order placement.
"""

import os
import time
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


TRADOVATE_DEMO_BASE = "https://demo.tradovateapi.com/v1"
TRADOVATE_LIVE_BASE = "https://live.tradovateapi.com/v1"


class TradovateClient:
    """Tradovate REST API client with token caching and renewal."""

    def __init__(self):
        self.username = os.getenv("TRADOVATE_USERNAME")
        self.password = os.getenv("TRADOVATE_PASSWORD")
        self.app_id = os.getenv("TRADOVATE_APP_ID", "AlphaTrader")
        self.app_version = os.getenv("TRADOVATE_APP_VERSION", "1.0")
        self.device_id = os.getenv("TRADOVATE_DEVICE_ID", "alphatrader-device-001")
        self.cid = os.getenv("TRADOVATE_CID")
        self.sec = os.getenv("TRADOVATE_SEC")
        self.account_id = os.getenv("TRADOVATE_ACCOUNT_ID")
        self.account_spec = os.getenv("TRADOVATE_ACCOUNT_SPEC") or self.username
        self.demo = os.getenv("TRADOVATE_DEMO", "true").lower() in ("1", "true", "yes")
        self.base_url = TRADOVATE_DEMO_BASE if self.demo else TRADOVATE_LIVE_BASE

        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None
        self._warned_once = False

    @property
    def is_configured(self) -> bool:
        """Return True when the minimum credentials are present."""
        return bool(self.username and self.password and self.app_id and self.device_id)

    def _warn_if_unconfigured(self) -> None:
        if not self.is_configured and not self._warned_once:
            logger.warning(
                "Tradovate credentials not configured. Set TRADOVATE_USERNAME, "
                "TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_DEVICE_ID, and "
                "TRADOVATE_ACCOUNT_ID in .env to enable Apex/Tradovate trading."
            )
            self._warned_once = True

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return headers

    async def _ensure_authenticated(self) -> bool:
        """Authenticate or renew token if needed."""
        self._warn_if_unconfigured()
        if not self.is_configured:
            return False
        if self._access_token and self._token_expires_at and time.time() < self._token_expires_at - 60:
            return True

        body = {
            "name": self.username,
            "password": self.password,
            "appId": self.app_id,
            "appVersion": self.app_version,
            "deviceId": self.device_id,
        }
        if self.cid:
            body["cid"] = self.cid
        if self.sec:
            body["sec"] = self.sec

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/auth/accessTokenRequest",
                    json=body,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                ) as resp:
                    data = await resp.json()
                    if resp.status == 200 and data.get("accessToken"):
                        self._access_token = data["accessToken"]
                        # Tradovate tokens are typically valid for ~1 week; renew after 6 days.
                        self._token_expires_at = time.time() + (data.get("expirationTime", 6 * 24 * 3600))
                        logger.info("Tradovate authenticated successfully")
                        return True
                    else:
                        logger.error(f"Tradovate auth failed: {data}")
                        return False
        except Exception as e:
            logger.error(f"Tradovate auth error: {e}")
            return False

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Dict]:
        """Make an authenticated request."""
        if not await self._ensure_authenticated():
            return None
        url = f"{self.base_url}{path}"
        headers = self._headers()
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=headers, **kwargs) as resp:
                    if resp.status == 204:
                        return {}
                    data = await resp.json()
                    if not resp.ok:
                        logger.error(f"Tradovate API error {resp.status}: {data}")
                        return None
                    return data
        except Exception as e:
            logger.error(f"Tradovate request error {method} {path}: {e}")
            return None

    async def list_accounts(self) -> List[Dict]:
        """List Tradovate accounts."""
        data = await self._request("GET", "/account/list")
        return data or []

    async def get_account(self) -> Optional[Dict]:
        """Get the configured account, or first available."""
        if self.account_id:
            data = await self._request("GET", f"/account/item/{self.account_id}")
            if data:
                return data
        accounts = await self.list_accounts()
        return accounts[0] if accounts else None

    async def get_cash_balance(self) -> Optional[Dict]:
        """Get cash balance snapshot for the account."""
        account = await self.get_account()
        if not account:
            return None
        account_id = account.get("id")
        data = await self._request("GET", f"/cashBalance/getCashBalanceSnapshot/{account_id}")
        return data

    async def list_positions(self) -> List[Dict]:
        """List current positions."""
        data = await self._request("GET", "/position/list")
        if not data:
            return []
        # Filter by account if configured
        if self.account_id:
            data = [p for p in data if str(p.get("accountId")) == str(self.account_id)]
        return data

    async def list_orders(self) -> List[Dict]:
        """List working orders."""
        data = await self._request("GET", "/order/list")
        if not data:
            return []
        if self.account_id:
            data = [o for o in data if str(o.get("accountId")) == str(self.account_id)]
        return data

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "Market",
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "Day",
    ) -> Optional[Dict]:
        """Place an order on Tradovate.

        Args:
            symbol: Contract symbol, e.g. "MESU5" or "NQZ5"
            side: "Buy" or "Sell"
            quantity: Number of contracts
            order_type: Market, Limit, Stop, StopLimit, etc.
            price: Limit price (required for Limit/StopLimit)
            stop_price: Stop price (required for Stop/StopLimit)
            time_in_force: Day, GTC, IOC, FOK
        """
        self._warn_if_unconfigured()
        if not self.is_configured:
            return {"error": "Tradovate not configured", "status": "failed"}

        account = await self.get_account()
        if not account:
            return {"error": "No Tradovate account available", "status": "failed"}

        body = {
            "accountSpec": self.account_spec or account.get("name"),
            "accountId": account.get("id"),
            "action": side.capitalize(),
            "symbol": symbol.upper(),
            "orderQty": int(quantity),
            "orderType": order_type.capitalize(),
            "timeInForce": time_in_force,
            "isAutomated": True,
        }
        if price is not None:
            body["price"] = float(price)
        if stop_price is not None:
            body["stopPrice"] = float(stop_price)

        logger.info(f"Tradovate: placing {side} {quantity} {symbol} {order_type} order")
        result = await self._request("POST", "/order/placeorder", json=body)
        if result is None:
            return {"error": "Tradovate order request failed", "status": "failed"}
        return result

    async def liquidate_position(self, position_id: int) -> Optional[Dict]:
        """Liquidate a position by ID."""
        body = {"positionId": position_id}
        return await self._request("POST", "/order/liquidateposition", json=body)


# Singleton
_tradovate_client: Optional[TradovateClient] = None


def get_tradovate_client() -> TradovateClient:
    global _tradovate_client
    if _tradovate_client is None:
        _tradovate_client = TradovateClient()
    return _tradovate_client


def _normalize_position(pos: Dict) -> Dict:
    """Normalize a Tradovate position to the platform's common format."""
    side = pos.get("netPos", 0)
    return {
        "venue": "Apex/Tradovate",
        "symbol": pos.get("contractDescription") or pos.get("symbol", ""),
        "side": "long" if side > 0 else "short" if side < 0 else "flat",
        "quantity": abs(side),
        "size": abs(side),
        "entry_price": pos.get("avgPrice") or pos.get("avgFillPrice", 0),
        "current_price": pos.get("lastPrice") or pos.get("markPrice", 0),
        "pnl": pos.get("unrealizedPnl", 0),
        "pnl_pct": 0.0,
        "raw": pos,
    }


async def tradovate_get_positions() -> List[Dict]:
    """Get normalized positions from Tradovate."""
    client = get_tradovate_client()
    if not client.is_configured:
        return []
    positions = await client.list_positions()
    return [_normalize_position(p) for p in positions if p.get("netPos", 0) != 0]


async def tradovate_get_account_summary() -> Dict:
    """Get account balance and summary info."""
    client = get_tradovate_client()
    if not client.is_configured:
        return {}
    account = await client.get_account()
    balance = await client.get_cash_balance()
    return {
        "account": account,
        "cash_balance": balance,
        "demo": client.demo,
        "base_url": client.base_url,
    }


async def tradovate_place_trade(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "Market",
    price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> Dict:
    """Place a trade through Tradovate."""
    client = get_tradovate_client()
    if not client.is_configured:
        return {"error": "Tradovate not configured", "status": "failed"}

    # Normalize side to Buy/Sell
    side_map = {"long": "Buy", "short": "Sell", "buy": "Buy", "sell": "Sell"}
    tv_side = side_map.get(side.lower(), side.capitalize())

    result = await client.place_order(
        symbol=symbol,
        side=tv_side,
        quantity=quantity,
        order_type=order_type,
        price=price,
        stop_price=stop_price,
    )
    return result or {"error": "Unknown Tradovate error", "status": "failed"}


async def tradovate_get_orders() -> List[Dict]:
    """Get working orders from Tradovate."""
    client = get_tradovate_client()
    if not client.is_configured:
        return []
    return await client.list_orders()
