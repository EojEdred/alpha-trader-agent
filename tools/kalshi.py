"""
Kalshi event-market adapter (API v2).

Uses the official Kalshi trading API directly via httpx. The legacy `kalshi`
PyPI package only supports v1/email-password auth, so this module targets the
current v2 key-based API.

Required environment variables:
    KALSHI_API_KEY          # from Kalshi Settings -> API Keys
    KALSHI_API_URL          # optional, defaults to https://trading-api.kalshi.com/trade-api/v2
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx
from loguru import logger

DEFAULT_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"


class KalshiError(Exception):
    """Raised when a Kalshi API call fails."""

    def __init__(self, message: str, status: Optional[int] = None, response: Any = None):
        super().__init__(message)
        self.status = status
        self.response = response


class KalshiClient:
    """Async Kalshi v2 API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.api_key = api_key or os.getenv("KALSHI_API_KEY")
        self.base_url = (base_url or os.getenv("KALSHI_API_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = float(timeout or os.getenv("KALSHI_TIMEOUT_SECONDS", "30"))
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: Dict[str, str] = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "KalshiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if not self.api_key:
            raise KalshiError("KALSHI_API_KEY not configured")
        try:
            resp = await self._get_client().request(method, path, params=params, json=json)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            text = e.response.text
            try:
                body = e.response.json()
            except Exception:
                body = text
            logger.error(f"Kalshi API error {e.response.status_code}: {text[:200]}")
            raise KalshiError(str(body), status=e.response.status_code, response=body) from e
        except Exception as e:
            logger.error(f"Kalshi request failed: {e}")
            raise KalshiError(str(e)) from e

    # ------------------------------------------------------------------
    # Account / exchange
    # ------------------------------------------------------------------
    async def get_exchange_status(self) -> Dict[str, Any]:
        """Return Kalshi exchange status."""
        return await self._request("GET", "/exchange/status")

    async def get_balance(self) -> Dict[str, Any]:
        """Return account balance and withdrawal info."""
        return await self._request("GET", "/portfolio/balance")

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Return all open market positions."""
        data = await self._request("GET", "/portfolio/positions")
        positions = data.get("positions", []) if isinstance(data, dict) else []
        normalized = []
        for pos in positions:
            normalized.append({
                "venue": "Kalshi",
                "symbol": pos.get("ticker", ""),
                "side": "yes" if pos.get("position", 0) > 0 else "no",
                "size": abs(pos.get("position", 0)),
                "entry": pos.get("average_price", 0),
                "current": pos.get("market_price", 0),
                "pnl": pos.get("unrealized_pnl", 0),
            })
        return normalized

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------
    async def get_markets(
        self,
        limit: int = 100,
        status: Optional[str] = None,
        event_ticker: Optional[str] = None,
        series_ticker: Optional[str] = None,
        cursor: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List markets with optional filters."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if event_ticker:
            params["event_ticker"] = event_ticker
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> Dict[str, Any]:
        """Return data for a single market."""
        return await self._request("GET", f"/markets/{ticker}")

    async def get_market_orderbook(self, ticker: str) -> Dict[str, Any]:
        """Return cached orderbook for a market."""
        return await self._request("GET", f"/markets/{ticker}/orderbook")

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    async def place_order(
        self,
        ticker: str,
        side: str,
        count: int,
        price: Optional[int] = None,
        client_order_id: Optional[str] = None,
        expiration_ts: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Place a Kalshi order.

        Args:
            ticker: Market ticker (e.g., "INXW-25-DEC31-T250").
            side: "yes" or "no".
            count: Number of contracts.
            price: Limit price in cents (0-100). Omit for market order if supported.
            client_order_id: Optional client ID for idempotency.
            expiration_ts: Optional Unix seconds order expiration.
        """
        if side.lower() not in ("yes", "no"):
            raise KalshiError("side must be 'yes' or 'no'")
        if count <= 0:
            raise KalshiError("count must be positive")

        payload: Dict[str, Any] = {
            "ticker": ticker,
            "side": side.lower(),
            "count": count,
            "client_order_id": client_order_id or str(uuid4())[:32],
        }
        if price is not None:
            payload["price"] = price
        if expiration_ts is not None:
            payload["expiration_ts"] = expiration_ts

        logger.info(f"Kalshi: placing {side.upper()} {count} @{price or 'MKT'} on {ticker}")
        data = await self._request("POST", "/orders", json=payload)
        order = data.get("order", data)
        return {
            "status": "filled" if order.get("status") == "executed" else "pending",
            "order_id": order.get("order_id") or order.get("id"),
            "ticker": ticker,
            "side": side,
            "size": count,
            "price": price,
            "venue": "Kalshi",
            "executed_at": datetime.utcnow().isoformat(),
            "raw": data,
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        return await self._request("DELETE", f"/orders/{order_id}")

    async def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return orders with optional filters."""
        params: Dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        data = await self._request("GET", "/orders", params=params)
        return data.get("orders", []) if isinstance(data, dict) else []


# Singleton instance
_kalshi_client: Optional[KalshiClient] = None


def get_kalshi_client() -> KalshiClient:
    global _kalshi_client
    if _kalshi_client is None:
        _kalshi_client = KalshiClient()
    return _kalshi_client


async def kalshi_get_balance() -> Dict[str, Any]:
    return await get_kalshi_client().get_balance()


async def kalshi_get_positions() -> List[Dict[str, Any]]:
    return await get_kalshi_client().get_positions()


async def kalshi_get_markets(**kwargs) -> Dict[str, Any]:
    return await get_kalshi_client().get_markets(**kwargs)


async def kalshi_get_market(ticker: str) -> Dict[str, Any]:
    return await get_kalshi_client().get_market(ticker)


async def kalshi_place_order(**kwargs) -> Dict[str, Any]:
    return await get_kalshi_client().place_order(**kwargs)


async def kalshi_cancel_order(order_id: str) -> Dict[str, Any]:
    return await get_kalshi_client().cancel_order(order_id)
