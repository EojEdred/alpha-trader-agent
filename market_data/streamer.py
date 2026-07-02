"""
Market Data Streamer

Real-time WebSocket streaming for live market data.

Supports:
- WebSocket connections (WebSocketClient)
- Real-time price updates
- Subscriptions to multiple symbols
- Reconnection on disconnect
- Data callbacks to subscribers
"""

import asyncio
import json
from typing import Dict, Any, List, Callable, Optional, Set
from datetime import datetime
from loguru import logger
import websockets


class MarketDataStreamer:
    """
    Real-time market data streaming via WebSocket.

    Features:
    - Subscribe to multiple symbols
    - Real-time price/quote updates
    - Automatic reconnection
    - Subscriber callbacks
    - Connection status tracking
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        stream_config = self.config.get("streaming", {})
        self.enabled = stream_config.get("enabled", False)
        self.reconnect_interval = stream_config.get("reconnect_interval_seconds", 5)
        self.max_reconnect_attempts = stream_config.get("max_reconnect_attempts", 10)

        self.subscriptions: Set[str] = set()
        self.callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.connected = False
        self.reconnect_attempts = 0

    def subscribe(self, symbol: str, callback: Callable[[str, Dict[str, Any]], None]):
        """
        Subscribe to real-time updates for a symbol.

        Args:
            symbol: Trading symbol (e.g., SPY, QQQ, NQ)
            callback: Function to call when data arrives: callback(symbol, data)
        """
        self.subscriptions.add(symbol)
        self.callbacks.append(callback)

        logger.info(f"Subscribed to {symbol}. Total subscribers: {len(self.callbacks)}")

    def unsubscribe(self, symbol: Optional[str] = None):
        """
        Unsubscribe from symbol (or all if symbol is None).

        Args:
            symbol: Symbol to unsubscribe (None = all)
        """
        if symbol:
            self.subscriptions.discard(symbol)
            logger.info(f"Unsubscribed from {symbol}")
        else:
            self.subscriptions.clear()
            logger.info("Unsubscribed from all symbols")

    async def connect(self, uri: str) -> bool:
        """
        Connect to WebSocket server.

        Args:
            uri: WebSocket URI (e.g., wss://api.example.com/stream)

        Returns:
            True if connected successfully
        """
        if not self.enabled:
            logger.warning("Streaming is disabled in config")
            return False

        try:
            logger.info(f"Connecting to WebSocket: {uri}")
            self.ws = await websockets.connect(uri)
            self.connected = True
            self.reconnect_attempts = 0

            logger.info(f"Connected to {uri}")

            asyncio.create_task(self._listen())

            return True

        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            return False

    async def _listen(self):
        """Listen for incoming WebSocket messages."""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket connection closed")
            self.connected = False
            await self._reconnect()

        except Exception as e:
            logger.error(f"WebSocket listen error: {e}")
            self.connected = False
            await self._reconnect()

    async def _handle_message(self, data: Dict[str, Any]):
        """
        Handle incoming WebSocket message.

        Routes data to subscribed callbacks.
        """
        symbol = data.get("symbol")

        if not symbol:
            return

        if symbol not in self.subscriptions:
            logger.debug(f"Received data for unsubscribed symbol: {symbol}")
            return

        logger.debug(f"Received data for {symbol}: {data}")

        for callback in self.callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(symbol, data)
                else:
                    callback(symbol, data)

            except Exception as e:
                logger.error(f"Callback error for {symbol}: {e}")

    async def _reconnect(self):
        """Reconnect to WebSocket server."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                f"Max reconnect attempts reached: {self.max_reconnect_attempts}"
            )
            return

        self.reconnect_attempts += 1
        wait_time = self.reconnect_interval * self.reconnect_attempts

        logger.warning(
            f"Reconnecting in {wait_time}s (attempt {self.reconnect_attempts})..."
        )

        await asyncio.sleep(wait_time)

        stream_config = self.config.get("streaming", {})
        uri = stream_config.get("websocket_uri")

        if uri:
            await self.connect(uri)

    async def disconnect(self):
        """Disconnect from WebSocket server."""
        if self.ws:
            await self.ws.close()
            self.connected = False
            logger.info("Disconnected from WebSocket")

    def get_status(self) -> Dict[str, Any]:
        """Get connection status."""
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "subscribed_symbols": list(self.subscriptions),
            "subscribers": len(self.callbacks),
            "reconnect_attempts": self.reconnect_attempts,
        }


class MockStreamer:
    """
    Mock streamer for testing without WebSocket connection.

    Simulates real-time data with periodic updates.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.subscriptions: Set[str] = set()
        self.callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

        self._running = False
        self._task = None

    def subscribe(self, symbol: str, callback: Callable[[str, Dict[str, Any]], None]):
        """Subscribe to simulated updates."""
        self.subscriptions.add(symbol)
        self.callbacks.append(callback)

        logger.info(f"Mock subscribed to {symbol}")

    def unsubscribe(self, symbol: Optional[str] = None):
        """Unsubscribe from symbol (or all if symbol is None)."""
        if symbol:
            self.subscriptions.discard(symbol)
        else:
            self.subscriptions.clear()

    async def connect(self, uri: Optional[str] = None) -> bool:
        """Start mock streaming (uri ignored)."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._stream_loop())

        return True

    async def _stream_loop(self):
        """Stream simulated data to subscribers."""
        from market_data.fetcher import MarketDataFetcher

        fetcher = MarketDataFetcher(self.config)

        while self._running:
            for symbol in self.subscriptions:
                try:
                    data = await fetcher.fetch_symbol_data(symbol)

                    for callback in self.callbacks:
                        try:
                            await callback(symbol, data)
                        except Exception as e:
                            logger.error(f"Mock callback error: {e}")

            except Exception as e:
                logger.error(f"Mock stream error for {symbol}: {e}")

            await asyncio.sleep(60)

    async def disconnect(self):
        """Stop mock streaming."""
        self._running = False

        if self._task:
            self._task.cancel()
            logger.info("Mock streaming stopped")


async def get_streamer(config: Dict[str, Any] = None) -> MarketDataStreamer:
    """
    Get streamer instance (real or mock based on config).
    """
    if config is None:
        from standalone.config import Config

        config = Config.load().__dict__

    stream_config = config.get("streaming", {})

    if stream_config.get("use_mock", False):
        return MockStreamer(config)
    else:
        return MarketDataStreamer(config)
