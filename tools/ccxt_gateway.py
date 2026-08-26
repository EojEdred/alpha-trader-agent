"""
CCXT Crypto Gateway for Alpha Trader

Normalized execution gateway for centralized crypto exchanges.
Supports Binance, OKX, Bybit, Hyperliquid, Gate, MEXC, and any other
exchange supported by CCXT.

Configured via config.yaml under execution_modes.venues or crypto_exchanges.

Usage:
    from tools.ccxt_gateway import CCXTGateway

    gateway = CCXTGateway("binance", config)
    await gateway.load_markets()
    balance = await gateway.get_balance()
    order = await gateway.create_market_buy("BTC/USDT", 0.001)
"""

import os
from typing import Any, Dict, List, Optional

from loguru import logger


try:
    import ccxt
    import ccxt.async_support as ccxt_async
    _CCXT_AVAILABLE = True
except ImportError:
    ccxt = None
    ccxt_async = None
    _CCXT_AVAILABLE = False


class CCXTGatewayError(Exception):
    """Raised when a CCXT gateway operation fails."""

    def __init__(self, message: str, exchange: Optional[str] = None):
        super().__init__(message)
        self.exchange = exchange


class CCXTGateway:
    """
    Async gateway wrapper around CCXT exchange clients.

    Handles credentials, market loading, symbol normalization, and order
    creation with basic pre-trade guardrails.
    """

    SUPPORTED_EXCHANGES = [
        "binance",
        "okx",
        "bybit",
        "hyperliquid",
        "gate",
        "mexc",
        "coinbase",
        "kraken",
        "kucoin",
    ]

    def __init__(self, exchange_id: str, config: Optional[Dict[str, Any]] = None):
        self.exchange_id = exchange_id.lower()
        self.config = config or {}
        self.client = self._create_client()

    def _create_client(self):
        if not _CCXT_AVAILABLE:
            raise CCXTGatewayError("ccxt not installed", self.exchange_id)

        if self.exchange_id not in ccxt_async.exchanges:
            raise CCXTGatewayError(f"Unsupported exchange: {self.exchange_id}", self.exchange_id)

        exchange_config = self._get_exchange_config()
        api_key = exchange_config.get("api_key") or os.environ.get(f"{self.exchange_id.upper()}_API_KEY")
        secret = exchange_config.get("secret") or os.environ.get(f"{self.exchange_id.upper()}_API_SECRET")
        password = exchange_config.get("password") or os.environ.get(f"{self.exchange_id.upper()}_PASSWORD")
        sandbox = bool(exchange_config.get("sandbox", False))

        options = {}
        if sandbox:
            options["defaultType"] = "spot"

        cls = getattr(ccxt_async, self.exchange_id)
        client = cls(
            {
                "apiKey": api_key,
                "secret": secret,
                "password": password,
                "enableRateLimit": True,
                "options": options,
                "sandbox": sandbox,
            }
        )
        if sandbox and hasattr(client, "set_sandbox_mode"):
            client.set_sandbox_mode(True)
        return client

    def _get_exchange_config(self) -> Dict[str, Any]:
        """Load config for this exchange from config.yaml."""
        venues = self.config.get("execution_modes", {}).get("venues", {})
        if self.exchange_id in venues:
            return venues[self.exchange_id]

        crypto_exchanges = self.config.get("crypto_exchanges", [])
        for ex in crypto_exchanges:
            if isinstance(ex, dict) and ex.get("name", "").lower() == self.exchange_id:
                return ex

        return {}

    async def load_markets(self):
        """Load exchange markets. Required before most operations."""
        await self.client.load_markets()

    async def close(self):
        """Close the exchange client session."""
        await self.client.close()

    async def __aenter__(self):
        await self.load_markets()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account balance."""
        return await self.client.fetch_balance()

    async def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch ticker for a symbol."""
        return await self.client.fetch_ticker(symbol)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
    ) -> List[List[float]]:
        """Fetch OHLCV candles."""
        return await self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    # ------------------------------------------------------------------
    # Order operations
    # ------------------------------------------------------------------

    async def create_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        amount: float,
        order_type: str = "market",
        price: Optional[float] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an order with guardrails.

        Args:
            symbol: CCXT market symbol (e.g. BTC/USDT).
            side: "buy" or "sell".
            amount: Order amount in base currency.
            order_type: "market", "limit", "stop_loss", etc.
            price: Limit price (required for limit orders).
            params: Additional exchange-specific params.
        """
        params = params or {}
        side = side.lower()
        order_type = order_type.lower()

        if side not in ("buy", "sell"):
            raise CCXTGatewayError(f"Invalid side: {side}", self.exchange_id)

        market = self.client.market(symbol)
        if market is None:
            raise CCXTGatewayError(f"Market not found: {symbol}", self.exchange_id)

        # Minimum amount guardrail
        min_amount = market.get("limits", {}).get("amount", {}).get("min")
        if min_amount is not None and amount < min_amount:
            raise CCXTGatewayError(
                f"Amount {amount} below minimum {min_amount} for {symbol}",
                self.exchange_id,
            )

        # Price guardrail for limit orders
        if order_type == "limit" and price is None:
            raise CCXTGatewayError("Limit order requires price", self.exchange_id)

        logger.info(
            f"CCXT {self.exchange_id}: {side} {amount} {symbol} @ {order_type}"
        )
        return await self.client.create_order(
            symbol, order_type, side, amount, price, params
        )

    async def create_market_buy(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Convenience: market buy."""
        return await self.create_order(symbol, "buy", amount, "market")

    async def create_market_sell(self, symbol: str, amount: float) -> Dict[str, Any]:
        """Convenience: market sell."""
        return await self.create_order(symbol, "sell", amount, "market")

    async def cancel_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Cancel an open order."""
        return await self.client.cancel_order(order_id, symbol)

    async def get_order(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """Fetch order status."""
        return await self.client.fetch_order(order_id, symbol)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch open orders."""
        return await self.client.fetch_open_orders(symbol)

    # ------------------------------------------------------------------
    # Leverage / margin (perps)
    # ------------------------------------------------------------------

    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        """Set leverage for a derivatives market."""
        return await self.client.set_leverage(leverage, symbol)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def normalize_symbol(self, symbol: str) -> str:
        """Try to normalize a symbol to CCXT format."""
        # Common transformations
        s = symbol.upper().replace("/", "").replace("-", "")
        # Try common patterns
        for sep in ("/", "-", ""):
            candidate = f"BTC{sep}USDT" if s == "BTCUSDT" else s
            if candidate in self.client.markets:
                return candidate
        if s in self.client.markets:
            return s
        return symbol
