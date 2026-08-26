"""
Unusual Whales API Integration for Alpha Trader

Provides alternative-data alpha signals:
- Options flow and sweep detection
- Greek exposure (GEX) by strike/expiry
- Dark pool prints and price-level volume
- Market Tide and Net Premium/Net Flow
- SPX Periscope (market-maker exposure)

Configured via config.yaml under market_data_apis.options_flow or
mcp_servers.unusual_whales.

Usage:
    from tools.unusual_whales import UnusualWhalesClient

    uw = UnusualWhalesClient(config)
    flow = await uw.options_flow("AAPL")
    gex = await uw.gamma_exposure("SPY")
"""

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from loguru import logger

from models import EvidenceItem, generate_evidence_id
from models.decision_schemas import AnalystReport, Confidence, Direction


DEFAULT_BASE_URL = "https://api.unusualwhales.com"


class UnusualWhalesError(Exception):
    """Raised when an Unusual Whales API call fails."""

    def __init__(self, message: str, endpoint: Optional[str] = None, status: Optional[int] = None):
        super().__init__(message)
        self.endpoint = endpoint
        self.status = status


class UnusualWhalesClient:
    """
    Async HTTP client for the Unusual Whales REST API.

    Falls back to neutral/empty results when no API key is configured or the
    API is unreachable, so the rest of the Alpha Trader pipeline keeps running.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        api_config = self.config.get("market_data_apis", {}).get("options_flow", {})
        self.api_key = api_config.get("api_key") or os.environ.get("UNUSUAL_WHALES_API_KEY")
        self.base_url = api_config.get("base_url", DEFAULT_BASE_URL).rstrip("/")
        self.enabled = bool(api_config.get("enabled", False)) and bool(self.api_key)
        self.timeout = float(api_config.get("timeout_seconds", 30.0))
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Make an authenticated GET request and return JSON, or None on failure."""
        if not self.enabled:
            logger.debug(f"Unusual Whales disabled; skipping {endpoint}")
            return None

        try:
            response = await self._get_client().get(endpoint, params=params)
            if response.status_code == 429:
                logger.warning(f"Unusual Whales rate limit hit on {endpoint}")
                raise UnusualWhalesError("Rate limited", endpoint=endpoint, status=429)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.warning(f"Unusual Whales {endpoint} returned {e.response.status_code}")
            raise UnusualWhalesError(
                f"HTTP {e.response.status_code}",
                endpoint=endpoint,
                status=e.response.status_code,
            )
        except Exception as e:
            logger.warning(f"Unusual Whales {endpoint} request failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Core endpoints
    # ------------------------------------------------------------------

    async def options_flow(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
        min_premium: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch recent options flow.

        Args:
            symbol: Filter by ticker (optional).
            limit: Max number of flow records.
            min_premium: Minimum premium threshold.
        """
        params: Dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if min_premium:
            params["min_premium"] = min_premium

        return await self._get("/api/flow", params=params)

    async def gamma_exposure(
        self,
        symbol: str,
        expiry: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch gamma exposure (GEX) for a symbol.

        Args:
            symbol: Underlying ticker (e.g. SPY, QQQ).
            expiry: Option expiration date (YYYY-MM-DD), optional.
        """
        params: Dict[str, Any] = {"symbol": symbol}
        if expiry:
            params["expiry"] = expiry

        return await self._get("/api/gex", params=params)

    async def dark_pool(self, symbol: Optional[str] = None, limit: int = 50) -> Optional[Dict[str, Any]]:
        """Fetch dark pool prints, optionally filtered by symbol."""
        params: Dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        return await self._get("/api/dark-pool", params=params)

    async def market_tide(self) -> Optional[Dict[str, Any]]:
        """Fetch Market Tide (aggregate options sentiment)."""
        return await self._get("/api/market-tide")

    async def spx_periscope(self) -> Optional[Dict[str, Any]]:
        """Fetch SPX Periscope (1-min market-maker exposure)."""
        return await self._get("/api/spx-periscope")

    async def unusual_options_activity(
        self,
        symbol: str,
        limit: int = 20,
    ) -> Optional[Dict[str, Any]]:
        """Fetch unusual options activity for a symbol."""
        return await self._get(
            f"/api/screener/option-contracts/{symbol}",
            params={"limit": limit},
        )

    # ------------------------------------------------------------------
    # Alpha Trader native outputs
    # ------------------------------------------------------------------

    async def flow_evidence(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[EvidenceItem]:
        """
        Convert options flow into a list of EvidenceItems.

        Each flow record becomes its own evidence item so the ResearchManager
        can weigh individual flow signals.
        """
        data = await self.options_flow(symbol=symbol, limit=limit)
        if data is None:
            return []

        records = data.get("data", data.get("flow", data.get("results", [])))
        if not isinstance(records, list):
            records = [records]

        evidence: List[EvidenceItem] = []
        for record in records[:limit]:
            if not isinstance(record, dict):
                continue
            sym = record.get("symbol", record.get("ticker", symbol or "UNKNOWN"))
            side = str(record.get("side", "unknown")).lower()
            premium = record.get("premium", 0)
            size = record.get("size", 0)
            sentiment = record.get("sentiment", "neutral")

            snippet = (
                f"{side.upper()} {sym} {record.get('strike', '')} "
                f"{record.get('expiry', '')} premium=${premium} size={size} "
                f"sentiment={sentiment}"
            ).strip()

            confidence = self._flow_confidence(record)
            tags = ["unusual_whales", "options_flow", sym]
            if record.get("sweep"):
                tags.append("sweep")
            if record.get("block"):
                tags.append("block")

            evidence.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"https://unusualwhales.com/flow/{sym}",
                    title=f"UW Flow: {sym}",
                    snippet=snippet[:400],
                    timestamp=datetime.utcnow(),
                    confidence=confidence,
                    tags=tags,
                )
            )

        return evidence

    async def gex_analyst_report(
        self,
        symbol: str,
        expiry: Optional[str] = None,
    ) -> AnalystReport:
        """
        Convert gamma exposure data into an AnalystReport.

        High positive net gamma near price → pinning / support-resistance levels.
        High negative net gamma → volatility expansion risk.
        """
        data = await self.gamma_exposure(symbol, expiry)
        if data is None:
            return AnalystReport(
                agent_name="unusual_whales_gex",
                symbol=symbol,
                direction=Direction.NEUTRAL,
                confidence=0.0,
                conviction_level=Confidence.LOW,
                key_points=["GEX data unavailable"],
                risks=["No gamma exposure data received"],
                timeframe="1d",
                evidence={},
                reasoning="Unusual Whales GEX endpoint did not return data.",
            )

        net_gex = self._extract_numeric(data, "net_gex", "total_gex", "gamma")
        price = self._extract_numeric(data, "price", "spot_price", "underlying_price")
        key_levels = data.get("key_levels", data.get("strikes", []))

        if net_gex is None:
            direction = Direction.NEUTRAL
            confidence = 0.5
        else:
            # Heuristic: large positive GEX can act as a magnet/pin;
            # large negative GEX can lead to explosive moves.
            if net_gex > 0:
                direction = Direction.NEUTRAL  # pinning, not directional
                confidence = min(0.8, abs(net_gex) / 1e9)
            else:
                direction = Direction.NEUTRAL
                confidence = min(0.75, abs(net_gex) / 1e9)

        conviction = (
            Confidence.HIGH if confidence > 0.8
            else Confidence.MEDIUM if confidence > 0.5
            else Confidence.LOW
        )

        key_points = [
            f"Net GEX: {net_gex}",
            f"Spot price: {price}",
        ]
        if isinstance(key_levels, list) and key_levels:
            key_points.append(f"Key gamma strikes: {key_levels[:10]}")

        reasoning = (
            f"Gamma exposure for {symbol} shows net GEX of {net_gex}. "
            f"High positive GEX tends to create pinning behavior; "
            f"high negative GEX increases volatility expansion risk."
        )

        return AnalystReport(
            agent_name="unusual_whales_gex",
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            conviction_level=conviction,
            key_points=key_points,
            risks=["GEX can flip intraday", "Dealer hedging flows are estimates"],
            timeframe="1d",
            evidence={"raw": data},
            reasoning=reasoning,
        )

    async def dark_pool_evidence(
        self,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[EvidenceItem]:
        """Convert dark pool prints into EvidenceItems."""
        data = await self.dark_pool(symbol=symbol, limit=limit)
        if data is None:
            return []

        records = data.get("data", data.get("prints", data.get("results", [])))
        if not isinstance(records, list):
            records = [records]

        evidence: List[EvidenceItem] = []
        for record in records[:limit]:
            if not isinstance(record, dict):
                continue
            sym = record.get("symbol", symbol or "UNKNOWN")
            price = record.get("price", "N/A")
            size = record.get("size", 0)
            premium = record.get("premium", price * size if isinstance(price, (int, float)) else 0)
            snippet = f"Dark pool print: {sym} @ {price} size={size} premium=${premium:,.0f}"
            evidence.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"https://unusualwhales.com/dark-pool/{sym}",
                    title=f"UW Dark Pool: {sym}",
                    snippet=snippet[:400],
                    timestamp=datetime.utcnow(),
                    confidence=0.65,
                    tags=["unusual_whales", "dark_pool", sym],
                )
            )

        return evidence

    async def market_tide_evidence(self) -> Optional[EvidenceItem]:
        """Convert Market Tide into a macro EvidenceItem."""
        data = await self.market_tide()
        if data is None:
            return None

        net_premium = data.get("net_premium", data.get("net_flow", "N/A"))
        sentiment = "bullish" if isinstance(net_premium, (int, float)) and net_premium > 0 else "bearish"
        snippet = f"Market Tide: net premium={net_premium}, sentiment={sentiment}"

        return EvidenceItem(
            id=generate_evidence_id(),
            url="https://unusualwhales.com/market-tide",
            title="Unusual Whales Market Tide",
            snippet=snippet[:500],
            timestamp=datetime.utcnow(),
            confidence=0.7,
            tags=["unusual_whales", "market_tide", "macro"],
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flow_confidence(record: Dict[str, Any]) -> float:
        """Heuristic confidence score for an options flow record."""
        score = 0.6
        premium = record.get("premium", 0) or 0
        size = record.get("size", 0) or 0
        if premium > 100_000:
            score += 0.15
        if premium > 500_000:
            score += 0.1
        if record.get("sweep"):
            score += 0.1
        if record.get("block"):
            score += 0.05
        if size > 1000:
            score += 0.05
        return min(0.95, score)

    @staticmethod
    def _extract_numeric(data: Dict[str, Any], *keys: str) -> Optional[float]:
        """Try to extract a numeric value from a dict using several key names."""
        for key in keys:
            val = data.get(key)
            if isinstance(val, (int, float)):
                return float(val)
            if isinstance(val, str):
                try:
                    return float(val.replace(",", "").replace("$", ""))
                except ValueError:
                    continue
        return None
