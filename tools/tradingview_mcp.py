"""
TradingView MCP Integration for Alpha Trader

Wraps the tradingview-mcp-server tools and converts their outputs into
Alpha Trader native objects: EvidenceItem and AnalystReport.

Requires:
    pip install tradingview-mcp-server

Configured via config.yaml under mcp_servers.tradingview.

Usage:
    from tools.tradingview_mcp import TradingViewMCP

    tv = TradingViewMCP(config)
    report = await tv.analyze_symbol("AAPL")
    signals = await tv.scan_market("bollinger_breakout")
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from models import EvidenceItem, generate_evidence_id
from models.decision_schemas import AnalystReport, Confidence, Direction
from tools.mcp_client import MCPClient, MCPError


class TradingViewMCP:
    """
    High-level wrapper around the TradingView MCP server.

    All methods degrade gracefully if the MCP server is unavailable,
    returning low-confidence neutral results rather than crashing the pipeline.
    """

    SERVER_NAME = "tradingview"

    def __init__(self, config: Optional[Dict[str, Any]] = None, client: Optional[MCPClient] = None):
        self.config = config or {}
        self._client = client
        self._tools_cache: Optional[List[str]] = None

    def _get_client(self) -> MCPClient:
        if self._client is None:
            self._client = MCPClient(self.config)
        return self._client

    async def list_tools(self) -> List[str]:
        """List tool names available on the TradingView MCP server."""
        if self._tools_cache is not None:
            return self._tools_cache
        try:
            tools = await self._get_client().list_tools(self.SERVER_NAME)
            self._tools_cache = [t["name"] for t in tools]
            return self._tools_cache
        except MCPError as e:
            logger.warning(f"TradingView MCP list_tools failed: {e}")
            return []

    async def _call(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 60.0,
    ) -> Optional[Any]:
        """Call an MCP tool and return parsed JSON data, or None on failure."""
        try:
            result = await self._get_client().call_tool(
                server_name=self.SERVER_NAME,
                tool_name=tool_name,
                arguments=arguments or {},
                timeout_seconds=timeout_seconds,
            )
            if result.is_error:
                logger.warning(f"TradingView MCP {tool_name} returned error: {result.text}")
                return None
            return result.data if result.data is not None else result.text
        except MCPError as e:
            logger.warning(f"TradingView MCP {tool_name} failed: {e}")
            return None
        except Exception as e:
            logger.warning(f"Unexpected error calling TradingView MCP {tool_name}: {e}")
            return None

    # ------------------------------------------------------------------
    # Analyst-level methods
    # ------------------------------------------------------------------

    async def analyze_symbol(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        timeframe: str = "1d",
    ) -> AnalystReport:
        """
        Run TradingView's deep coin/symbol analysis and return an AnalystReport.

        The MCP tool `coin_analysis` works for stocks, crypto, and forex.
        """
        raw = await self._call(
            "coin_analysis",
            {"symbol": symbol, "exchange": exchange, "timeframe": timeframe},
        )

        return self._parse_analysis_to_report(symbol, raw, agent_name="tradingview_ta")

    async def analyze_multi_timeframe(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        timeframes: Optional[List[str]] = None,
    ) -> AnalystReport:
        """
        Analyze a symbol across multiple timeframes and return a consensus report.
        """
        timeframes = timeframes or ["1h", "4h", "1d"]
        raw = await self._call(
            "multi_timeframe_analysis",
            {"symbol": symbol, "exchange": exchange, "timeframes": timeframes},
        )
        return self._parse_analysis_to_report(
            symbol, raw, agent_name="tradingview_mtf"
        )

    async def multi_agent_debate(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        timeframe: str = "1d",
    ) -> AnalystReport:
        """
        Run the three-agent Technical/Sentiment/Risk debate and return consensus.
        """
        raw = await self._call(
            "multi_agent_analysis",
            {"symbol": symbol, "exchange": exchange, "timeframe": timeframe},
        )
        return self._parse_analysis_to_report(
            symbol, raw, agent_name="tradingview_debate"
        )

    async def combined_ta_news_sentiment(
        self,
        symbol: str,
        exchange: str = "NASDAQ",
        timeframe: str = "1d",
    ) -> AnalystReport:
        """
        Combine technical analysis with news and sentiment into one report.
        """
        raw = await self._call(
            "combined_analysis",
            {"symbol": symbol, "exchange": exchange, "timeframe": timeframe},
        )
        return self._parse_analysis_to_report(
            symbol, raw, agent_name="tradingview_combined"
        )

    # ------------------------------------------------------------------
    # Signal / evidence methods
    # ------------------------------------------------------------------

    async def scan_market(
        self,
        scan_type: str = "bollinger_breakout",
        market: str = "america",
        limit: int = 20,
    ) -> List[EvidenceItem]:
        """
        Run a TradingView scanner and return EvidenceItems.

        scan_type options include:
            bollinger_breakout, volume_breakout, top_gainers, top_losers,
            smart_volume_scan, consecutive_candles_scan
        """
        tool_map = {
            "bollinger_breakout": "bollinger_scan",
            "volume_breakout": "smart_volume_scan",
            "top_gainers": "fetch_trending_analysis",
            "top_losers": "fetch_trending_analysis",
            "smart_volume": "smart_volume_scan",
            "consecutive_candles": "scan_consecutive_candles",
        }
        tool_name = tool_map.get(scan_type, scan_type)

        # Build arguments per tool
        args: Dict[str, Any] = {"market": market, "limit": limit}
        if scan_type in ("top_gainers", "top_losers"):
            args["type"] = scan_type

        raw = await self._call(tool_name, args, timeout_seconds=90.0)
        if raw is None:
            return []

        return self._parse_scan_to_evidence(raw, scan_type)

    async def market_snapshot(self) -> Optional[EvidenceItem]:
        """Fetch a broad market snapshot as a single evidence item."""
        raw = await self._call("get_market_snapshot", {})
        if raw is None:
            return None

        summary = self._extract_summary(raw)
        return EvidenceItem(
            id=generate_evidence_id(),
            url="mcp://tradingview/market_snapshot",
            title="TradingView Market Snapshot",
            snippet=summary[:500],
            timestamp=datetime.utcnow(),
            confidence=0.75,
            tags=["tradingview", "macro", "snapshot"],
        )

    async def bitcoin_market_pulse(self) -> Optional[EvidenceItem]:
        """Fetch Bitcoin macro pulse as regime context."""
        raw = await self._call("bitcoin_market_pulse", {})
        if raw is None:
            return None

        summary = self._extract_summary(raw)
        return EvidenceItem(
            id=generate_evidence_id(),
            url="mcp://tradingview/bitcoin_market_pulse",
            title="Bitcoin Market Pulse",
            snippet=summary[:500],
            timestamp=datetime.utcnow(),
            confidence=0.7,
            tags=["tradingview", "crypto", "macro"],
        )

    # ------------------------------------------------------------------
    # Backtest methods
    # ------------------------------------------------------------------

    async def run_backtest(
        self,
        symbol: str,
        strategy: str = "rsi",
        timeframe: str = "1d",
        exchange: str = "NASDAQ",
    ) -> Optional[Dict[str, Any]]:
        """
        Run a TradingView-style backtest for a symbol/strategy.

        strategy options include: rsi, bollinger, macd, ema_cross, supertrend,
        donchian, rsi_pullback, keltner_breakout, triple_ema
        """
        return await self._call(
            "backtest_strategy",
            {
                "symbol": symbol,
                "strategy": strategy,
                "timeframe": timeframe,
                "exchange": exchange,
            },
            timeout_seconds=120.0,
        )

    async def compare_strategies(
        self,
        symbol: str,
        strategies: Optional[List[str]] = None,
        timeframe: str = "1d",
        exchange: str = "NASDAQ",
    ) -> Optional[Dict[str, Any]]:
        """Compare multiple strategies and return ranking."""
        strategies = strategies or ["rsi", "bollinger", "macd", "ema_cross"]
        return await self._call(
            "compare_strategies",
            {
                "symbol": symbol,
                "strategies": strategies,
                "timeframe": timeframe,
                "exchange": exchange,
            },
            timeout_seconds=120.0,
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_analysis_to_report(
        self,
        symbol: str,
        raw: Any,
        agent_name: str,
    ) -> AnalystReport:
        """Normalize TradingView analysis output to AnalystReport."""
        if raw is None:
            return AnalystReport(
                agent_name=agent_name,
                symbol=symbol,
                direction=Direction.NEUTRAL,
                confidence=0.0,
                conviction_level=Confidence.LOW,
                key_points=["TradingView MCP unavailable"],
                risks=["No data received from MCP server"],
                timeframe="unknown",
                evidence={},
                reasoning="The TradingView MCP server did not return a result.",
            )

        data = raw if isinstance(raw, dict) else {}
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"summary": raw}

        # Extract directional signal
        recommendation = str(data.get("recommendation", data.get("signal", "hold"))).lower()
        if "buy" in recommendation or "bull" in recommendation or "strong buy" in recommendation:
            direction = Direction.LONG
        elif "sell" in recommendation or "bear" in recommendation or "strong sell" in recommendation:
            direction = Direction.SHORT
        else:
            direction = Direction.NEUTRAL

        # Extract confidence
        confidence = float(data.get("confidence", data.get("score", 0.5)))
        confidence = max(0.0, min(1.0, confidence))

        conviction = (
            Confidence.HIGH if confidence > 0.8
            else Confidence.MEDIUM if confidence > 0.5
            else Confidence.LOW
        )

        # Extract key points
        key_points: List[str] = []
        for key in ("summary", "technical_summary", "sentiment_summary", "consensus"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                key_points.append(val.strip()[:300])
                break
        if not key_points:
            key_points.append(self._extract_summary(data)[:300])

        # Add indicator-driven bullets
        indicators = data.get("indicators", {})
        if isinstance(indicators, dict):
            for k, v in list(indicators.items())[:5]:
                key_points.append(f"{k}: {v}")

        # Risks
        risks = data.get("risks", [])
        if not isinstance(risks, list):
            risks = [str(risks)]
        if not risks:
            risks.append("No explicit risks returned by TradingView MCP")

        return AnalystReport(
            agent_name=agent_name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            conviction_level=conviction,
            key_points=key_points,
            risks=risks,
            timeframe=str(data.get("timeframe", "1d")),
            evidence={"raw": data},
            reasoning=self._extract_summary(data),
        )

    def _parse_scan_to_evidence(
        self,
        raw: Any,
        scan_type: str,
    ) -> List[EvidenceItem]:
        """Normalize scanner output to a list of EvidenceItems."""
        if raw is None:
            return []

        data = raw if isinstance(raw, dict) else {}
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return [
                    EvidenceItem(
                        id=generate_evidence_id(),
                        url="mcp://tradingview/scan",
                        title=f"TradingView {scan_type} scan",
                        snippet=raw[:500],
                        timestamp=datetime.utcnow(),
                        confidence=0.5,
                        tags=["tradingview", scan_type],
                    )
                ]

        results = data.get("results", data.get("stocks", data.get("data", [])))
        if not isinstance(results, list):
            results = [results]

        evidence_items: List[EvidenceItem] = []
        for idx, item in enumerate(results[:50]):
            if not isinstance(item, dict):
                continue
            symbol = item.get("symbol", item.get("ticker", f"item_{idx}"))
            snippet = self._extract_summary(item)
            confidence = float(item.get("score", item.get("confidence", 0.6)))
            confidence = max(0.0, min(1.0, confidence))

            evidence_items.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"mcp://tradingview/{scan_type}/{symbol}",
                    title=f"{scan_type}: {symbol}",
                    snippet=snippet[:400],
                    timestamp=datetime.utcnow(),
                    confidence=confidence,
                    tags=["tradingview", scan_type, symbol],
                )
            )

        return evidence_items

    @staticmethod
    def _extract_summary(data: Any) -> str:
        """Best-effort extraction of a human-readable summary from MCP output."""
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return str(data)

        for key in (
            "summary",
            "analysis",
            "recommendation",
            "consensus",
            "description",
            "message",
            "result",
        ):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return json.dumps(data, default=str)[:500]
