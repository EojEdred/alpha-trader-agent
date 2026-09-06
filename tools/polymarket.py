"""
Polymarket CLOB adapter.

Uses the official `py_clob_client` package to interact with Polymarket's
Central Limit Order Book. Read-only endpoints work without credentials;
trading requires a wallet private key and API credentials generated from
that wallet.

Required environment variables for trading:
    POLYMARKET_HOST              # optional, defaults to https://clob.polymarket.com
    POLYMARKET_CHAIN_ID          # optional, defaults to 137 (Polygon mainnet)
    POLYMARKET_PRIVATE_KEY       # wallet private key (0x...)
    POLYMARKET_API_KEY           # CLOB API key
    POLYMARKET_API_SECRET        # CLOB API secret
    POLYMARKET_API_PASSPHRASE    # CLOB API passphrase
"""

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds

    POLYMARKET_AVAILABLE = True
except ImportError:
    POLYMARKET_AVAILABLE = False
    ClobClient = None  # type: ignore
    ApiCreds = None  # type: ignore


DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_CHAIN_ID = 137


class PolymarketError(Exception):
    """Raised when a Polymarket operation fails."""


class PolymarketClient:
    """Polymarket CLOB client wrapper."""

    def __init__(
        self,
        host: Optional[str] = None,
        chain_id: Optional[int] = None,
        private_key: Optional[str] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        api_passphrase: Optional[str] = None,
    ):
        self.host = host or os.getenv("POLYMARKET_HOST", DEFAULT_HOST)
        self.chain_id = int(chain_id or os.getenv("POLYMARKET_CHAIN_ID", DEFAULT_CHAIN_ID))
        self.private_key = private_key or os.getenv("POLYMARKET_PRIVATE_KEY")
        self.api_key = api_key or os.getenv("POLYMARKET_API_KEY")
        self.api_secret = api_secret or os.getenv("POLYMARKET_API_SECRET")
        self.api_passphrase = api_passphrase or os.getenv("POLYMARKET_API_PASSPHRASE")
        self._client: Optional[Any] = None

    @property
    def is_configured(self) -> bool:
        """True when all trading credentials are present."""
        return bool(
            self.private_key and self.api_key and self.api_secret and self.api_passphrase
        )

    def _get_client(self) -> Any:
        if not POLYMARKET_AVAILABLE:
            raise PolymarketError("py_clob_client is not installed")
        if self._client is None:
            creds = None
            if self.api_key and self.api_secret and self.api_passphrase:
                creds = ApiCreds(
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    api_passphrase=self.api_passphrase,
                )
            self._client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=self.private_key,
                creds=creds,
            )
        return self._client

    async def _run_sync(self, fn, *args, **kwargs):
        """Run a synchronous CLOB call in the default executor."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ------------------------------------------------------------------
    # Read-only endpoints
    # ------------------------------------------------------------------
    async def get_ok(self) -> bool:
        """Health check."""
        try:
            await self._run_sync(self._get_client().get_ok)
            return True
        except Exception as e:
            logger.error(f"Polymarket health check failed: {e}")
            return False

    async def get_markets(self, active: bool = True, limit: int = 100) -> List[Dict[str, Any]]:
        """Return simplified markets."""
        try:
            # get_markets returns a dict with 'markets' list in py_clob_client.
            data = await self._run_sync(self._get_client().get_markets, active=active)
            if isinstance(data, dict):
                return data.get("markets", [])
            return data[:limit] if isinstance(data, list) else []
        except Exception as e:
            logger.error(f"Polymarket markets error: {e}")
            return []

    async def get_market(self, condition_id: str) -> Dict[str, Any]:
        """Return a single market by condition ID."""
        return await self._run_sync(self._get_client().get_market, condition_id=condition_id)

    async def get_order_book(self, token_id: str) -> Dict[str, Any]:
        """Return order book for an outcome token."""
        return await self._run_sync(self._get_client().get_order_book, token_id=token_id)

    async def get_price(self, token_id: str, side: str) -> Optional[float]:
        """Return the best price for a token side ('BUY' or 'SELL')."""
        try:
            return await self._run_sync(self._get_client().get_price, token_id=token_id, side=side)
        except Exception as e:
            logger.error(f"Polymarket price error: {e}")
            return None

    # ------------------------------------------------------------------
    # Account endpoints (require auth)
    # ------------------------------------------------------------------
    async def get_balance(self) -> Dict[str, Any]:
        """Return USDC balance and allowance."""
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        return await self._run_sync(self._get_client().get_balance_allowance)

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Return open positions from the exchange."""
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        try:
            positions = await self._run_sync(self._get_client().get_positions)
            normalized = []
            for pos in positions if isinstance(positions, list) else []:
                normalized.append({
                    "venue": "Polymarket",
                    "symbol": pos.get("asset_id") or pos.get("condition_id", ""),
                    "side": pos.get("side", ""),
                    "size": float(pos.get("size", 0)),
                    "entry": float(pos.get("avg_price", 0)),
                    "current": float(pos.get("market_price", 0)),
                    "pnl": float(pos.get("unrealized_pnl", 0)),
                })
            return normalized
        except Exception as e:
            logger.error(f"Polymarket positions error: {e}")
            return []

    async def get_orders(
        self,
        market: Optional[str] = None,
        active: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return open orders."""
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        from py_clob_client.clob_types import OpenOrderParams
        params = OpenOrderParams(market=market)
        return await self._run_sync(self._get_client().get_orders, params=params)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    async def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
    ) -> Dict[str, Any]:
        """
        Place a Polymarket limit order.

        Args:
            token_id: Outcome token ID (from market metadata).
            side: "BUY" or "SELL".
            size: Number of outcome tokens.
            price: Price in USDC (0.01 to 0.99).
        """
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        if side.upper() not in ("BUY", "SELL"):
            raise PolymarketError("side must be BUY or SELL")
        if size <= 0:
            raise PolymarketError("size must be positive")

        logger.info(f"Polymarket: placing {side.upper()} {size} @{price} on {token_id}")
        try:
            from py_clob_client.clob_types import OrderArgs
            order_args = OrderArgs(
                token_id=token_id,
                side=side.upper(),
                size=size,
                price=price,
            )
            resp = await self._run_sync(self._get_client().create_and_post_order, order_args=order_args)
            return {
                "status": "submitted",
                "order_id": resp.get("order_id") if isinstance(resp, dict) else resp,
                "token_id": token_id,
                "side": side.upper(),
                "size": size,
                "price": price,
                "venue": "Polymarket",
                "executed_at": datetime.utcnow().isoformat(),
                "raw": resp,
            }
        except Exception as e:
            logger.error(f"Polymarket order error: {e}")
            raise PolymarketError(str(e)) from e

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order."""
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        return await self._run_sync(self._get_client().cancel_order, order_id=order_id)

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders."""
        if not self.is_configured:
            raise PolymarketError("Polymarket trading credentials not configured")
        return await self._run_sync(self._get_client().cancel_all)


# Singleton instance
_polymarket_client: Optional[PolymarketClient] = None


def get_polymarket_client() -> PolymarketClient:
    global _polymarket_client
    if _polymarket_client is None:
        _polymarket_client = PolymarketClient()
    return _polymarket_client


async def polymarket_get_markets(**kwargs) -> List[Dict[str, Any]]:
    return await get_polymarket_client().get_markets(**kwargs)


async def polymarket_get_market(condition_id: str) -> Dict[str, Any]:
    return await get_polymarket_client().get_market(condition_id)


async def polymarket_get_order_book(token_id: str) -> Dict[str, Any]:
    return await get_polymarket_client().get_order_book(token_id)


async def polymarket_get_balance() -> Dict[str, Any]:
    return await get_polymarket_client().get_balance()


async def polymarket_get_positions() -> List[Dict[str, Any]]:
    return await get_polymarket_client().get_positions()


async def polymarket_place_order(**kwargs) -> Dict[str, Any]:
    return await get_polymarket_client().place_order(**kwargs)


async def polymarket_cancel_order(order_id: str) -> Dict[str, Any]:
    return await get_polymarket_client().cancel_order(order_id)
