"""
Crypto exchange adapter using CCXT.

Supports any exchange CCXT knows how to talk to. Configure via environment:

    CRYPTO_EXCHANGE=coinbase        # lowercase ccxt exchange id
    CRYPTO_API_KEY=...
    CRYPTO_API_SECRET=...
    CRYPTO_API_PASSPHRASE=...       # required by some exchanges (e.g., Coinbase Pro, OKX)
    CRYPTO_SANDBOX=false            # set true for testnets
"""

import asyncio
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

try:
    import ccxt

    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    ccxt = None  # type: ignore


class CryptoClientError(Exception):
    """Raised when a crypto operation fails."""


class CryptoClient:
    """Unified async wrapper around a CCXT exchange."""

    def __init__(
        self,
        exchange: Optional[str] = None,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        sandbox: Optional[bool] = None,
    ):
        self.exchange_id = (exchange or os.getenv("CRYPTO_EXCHANGE", "coinbase")).lower()
        self.api_key = api_key or os.getenv("CRYPTO_API_KEY")
        self.secret = secret or os.getenv("CRYPTO_API_SECRET")
        self.passphrase = passphrase or os.getenv("CRYPTO_API_PASSPHRASE")
        self.sandbox = sandbox if sandbox is not None else os.getenv("CRYPTO_SANDBOX", "false").lower() == "true"
        self._client: Optional[Any] = None

        if not CCXT_AVAILABLE:
            logger.warning("ccxt is not installed; crypto integration disabled")
        elif self.exchange_id not in ccxt.exchanges:
            raise CryptoClientError(f"Unsupported or unknown exchange: {self.exchange_id}")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.secret)

    def _get_client(self) -> Any:
        if not CCXT_AVAILABLE:
            raise CryptoClientError("ccxt is not installed")
        if self._client is None:
            cls = getattr(ccxt, self.exchange_id)
            config: Dict[str, Any] = {
                "apiKey": self.api_key,
                "secret": self.secret,
                "enableRateLimit": True,
            }
            if self.passphrase:
                config["password"] = self.passphrase
            if self.sandbox and hasattr(cls, "sandbox"):
                config["sandbox"] = True
                config["options"] = {"defaultType": "spot"}
            self._client = cls(config)
        return self._client

    async def _run_sync(self, fn, *args, **kwargs):
        """Run a synchronous ccxt call in the default executor."""
        return await asyncio.to_thread(fn, *args, **kwargs)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------
    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch 24h ticker for a symbol (e.g., BTC/USD)."""
        return await self._run_sync(self._get_client().fetch_ticker, symbol.upper())

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[List[float]]:
        """Fetch OHLCV candles as ccxt format [timestamp, open, high, low, close, volume]."""
        return await self._run_sync(self._get_client().fetch_ohlcv, symbol.upper(), timeframe, limit=limit)

    async def get_order_book(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Fetch order book."""
        return await self._run_sync(self._get_client().fetch_order_book, symbol.upper(), limit)

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------
    async def get_balance(self) -> Dict[str, Any]:
        """Fetch total and free balances."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        return await self._run_sync(self._get_client().fetch_balance)

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch open positions (for derivative exchanges)."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        try:
            positions = await self._run_sync(self._get_client().fetch_positions)
            normalized = []
            for pos in positions if isinstance(positions, list) else []:
                normalized.append({
                    "venue": self.exchange_id,
                    "symbol": pos.get("symbol", ""),
                    "side": pos.get("side", ""),
                    "size": float(pos.get("contracts", 0) or 0),
                    "entry": float(pos.get("entryPrice", 0) or 0),
                    "current": float(pos.get("markPrice", 0) or 0),
                    "pnl": float(pos.get("unrealizedPnl", 0) or 0),
                })
            return normalized
        except Exception as e:
            logger.error(f"Crypto positions error: {e}")
            return []

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    async def place_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
    ) -> Dict[str, Any]:
        """Place a market order."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        side = side.lower()
        if side not in ("buy", "sell"):
            raise CryptoClientError("side must be buy or sell")
        logger.info(f"Crypto: placing {side.upper()} market {amount} {symbol}")
        order = await self._run_sync(
            self._get_client().create_market_buy_order if side == "buy" else self._get_client().create_market_sell_order,
            symbol.upper(),
            amount,
        )
        return {
            "status": order.get("status", "submitted"),
            "order_id": order.get("id"),
            "symbol": symbol.upper(),
            "side": side,
            "amount": amount,
            "venue": self.exchange_id,
            "executed_at": datetime.utcnow().isoformat(),
            "raw": order,
        }

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
    ) -> Dict[str, Any]:
        """Place a limit order."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        side = side.lower()
        if side not in ("buy", "sell"):
            raise CryptoClientError("side must be buy or sell")
        logger.info(f"Crypto: placing {side.upper()} limit {amount} {symbol} @ {price}")
        order = await self._run_sync(
            self._get_client().create_limit_buy_order if side == "buy" else self._get_client().create_limit_sell_order,
            symbol.upper(),
            amount,
            price,
        )
        return {
            "status": order.get("status", "submitted"),
            "order_id": order.get("id"),
            "symbol": symbol.upper(),
            "side": side,
            "amount": amount,
            "price": price,
            "venue": self.exchange_id,
            "executed_at": datetime.utcnow().isoformat(),
            "raw": order,
        }

    async def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Cancel an order."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        return await self._run_sync(self._get_client().cancel_order, order_id, symbol.upper() if symbol else None)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return open orders."""
        if not self.is_configured:
            raise CryptoClientError("Crypto API credentials not configured")
        return await self._run_sync(self._get_client().fetch_open_orders, symbol.upper() if symbol else None)


# Singleton instance
_crypto_client: Optional[CryptoClient] = None


def get_crypto_client() -> CryptoClient:
    global _crypto_client
    if _crypto_client is None:
        _crypto_client = CryptoClient()
    return _crypto_client


async def crypto_get_ticker(symbol: str) -> Dict[str, Any]:
    return await get_crypto_client().get_ticker(symbol)


async def crypto_get_balance() -> Dict[str, Any]:
    return await get_crypto_client().get_balance()


async def crypto_get_positions() -> List[Dict[str, Any]]:
    return await get_crypto_client().get_positions()


async def crypto_place_market_order(**kwargs) -> Dict[str, Any]:
    return await get_crypto_client().place_market_order(**kwargs)


async def crypto_place_limit_order(**kwargs) -> Dict[str, Any]:
    return await get_crypto_client().place_limit_order(**kwargs)


async def crypto_cancel_order(order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
    return await get_crypto_client().cancel_order(order_id, symbol)
