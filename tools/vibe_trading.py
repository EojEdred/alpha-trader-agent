"""
Vibe-Trading Sidecar Integration for Alpha Trader

Wraps the vibe-trading MCP server and exposes its quant research tools:
- factor_analysis
- alpha_zoo
- run_shadow_backtest
- backtest
- analyze_options_payoff

Configured via config.yaml under mcp_servers.vibe_trading.

Usage:
    from tools.vibe_trading import VibeTradingSidecar

    vibe = VibeTradingSidecar(config)
    factor_report = await vibe.factor_analysis("AAPL")
    shadow = await vibe.shadow_backtest(journal_path="data/journal.csv")
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from models import EvidenceItem, generate_evidence_id
from models.decision_schemas import AnalystReport, Confidence, Direction
from tools.mcp_client import MCPClient


class VibeTradingSidecar:
    """
    High-level wrapper around the Vibe-Trading MCP server.

    Vibe-Trading is used as a sidecar research/backtest layer. It does not
    execute trades; it provides alpha signals, factor analysis, and backtests
    that feed into Alpha Trader's decision pipeline.
    """

    SERVER_NAME = "vibe_trading"

    def __init__(self, config: Optional[Dict[str, Any]] = None, client: Optional[MCPClient] = None):
        self.config = config or {}
        self._client = client

    def _get_client(self) -> MCPClient:
        if self._client is None:
            self._client = MCPClient(self.config)
        return self._client

    async def _call(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        timeout_seconds: float = 120.0,
    ) -> Optional[Any]:
        """Call a Vibe-Trading MCP tool and return parsed JSON."""
        try:
            result = await self._get_client().call_tool(
                server_name=self.SERVER_NAME,
                tool_name=tool_name,
                arguments=arguments or {},
                timeout_seconds=timeout_seconds,
            )
            if result.is_error:
                logger.warning(f"Vibe-Trading {tool_name} returned error: {result.text}")
                return None
            return result.data if result.data is not None else result.text
        except Exception as e:
            logger.warning(f"Vibe-Trading {tool_name} failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Research / alpha tools
    # ------------------------------------------------------------------

    async def factor_analysis(
        self,
        symbol: str,
        factors: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run factor analysis for a symbol.

        Args:
            symbol: Ticker to analyze.
            factors: List of factor names (e.g. ["momentum", "value", "volatility"]).
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
        """
        return await self._call(
            "factor_analysis",
            {
                "symbol": symbol,
                "factors": factors or ["momentum", "mean_reversion", "volatility"],
                "start_date": start_date,
                "end_date": end_date,
            },
        )

    async def alpha_zoo(
        self,
        symbol: str,
        alpha_names: Optional[List[str]] = None,
        benchmark: str = "SPY",
    ) -> Optional[Dict[str, Any]]:
        """
        Run Alpha Zoo benchmark for a symbol.

        Args:
            symbol: Ticker to analyze.
            alpha_names: Specific alphas to benchmark. If None, runs a default set.
            benchmark: Benchmark ticker.
        """
        return await self._call(
            "alpha_zoo",
            {
                "symbol": symbol,
                "alpha_names": alpha_names,
                "benchmark": benchmark,
            },
        )

    async def backtest(
        self,
        symbol: str,
        strategy: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run a Vibe-Trading backtest for a symbol/strategy.

        Args:
            symbol: Ticker.
            strategy: Strategy name or code.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
        """
        return await self._call(
            "backtest",
            {
                "symbol": symbol,
                "strategy": strategy,
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout_seconds=180.0,
        )

    async def analyze_options_payoff(
        self,
        underlying: str,
        legs: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze options strategy payoff.

        Args:
            underlying: Underlying ticker.
            legs: List of option legs, each with side, option_ticker, quantity.
        """
        return await self._call(
            "analyze_options_payoff",
            {"underlying": underlying, "legs": legs},
        )

    async def run_swarm(
        self,
        task: str,
        agents: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Run a Vibe-Trading agent swarm for a research task.

        Args:
            task: Natural-language research task.
            agents: Agent team preset (e.g. ["investment_committee"]).
        """
        return await self._call(
            "run_swarm",
            {"task": task, "agents": agents or ["investment_committee"]},
            timeout_seconds=180.0,
        )

    # ------------------------------------------------------------------
    # Shadow account / journal mining
    # ------------------------------------------------------------------

    async def shadow_backtest(
        self,
        journal_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Mine a trade journal for implicit rules and backtest them.

        Args:
            journal_path: Path to CSV trade journal.
            start_date: YYYY-MM-DD.
            end_date: YYYY-MM-DD.
        """
        return await self._call(
            "run_shadow_backtest",
            {
                "journal_path": journal_path,
                "start_date": start_date,
                "end_date": end_date,
            },
            timeout_seconds=180.0,
        )

    # ------------------------------------------------------------------
    # Alpha Trader native outputs
    # ------------------------------------------------------------------

    async def factor_analyst_report(
        self,
        symbol: str,
        factors: Optional[List[str]] = None,
    ) -> AnalystReport:
        """Convert factor analysis output into an AnalystReport."""
        raw = await self.factor_analysis(symbol, factors=factors)
        if raw is None:
            return AnalystReport(
                agent_name="vibe_trading_factor",
                symbol=symbol,
                direction=Direction.NEUTRAL,
                confidence=0.0,
                conviction_level=Confidence.LOW,
                key_points=["Factor analysis unavailable"],
                risks=["Vibe-Trading MCP not configured or failed"],
                timeframe="1d",
                evidence={},
                reasoning="Vibe-Trading factor_analysis did not return data.",
            )

        # Normalize direction from factor signals
        summary = self._extract_text(raw)
        signal = str(raw.get("signal", raw.get("recommendation", "neutral"))).lower()
        if "buy" in signal or "bull" in signal:
            direction = Direction.LONG
        elif "sell" in signal or "bear" in signal:
            direction = Direction.SHORT
        else:
            direction = Direction.NEUTRAL

        confidence = float(raw.get("confidence", raw.get("score", 0.5)))
        confidence = max(0.0, min(1.0, confidence))
        conviction = (
            Confidence.HIGH if confidence > 0.8
            else Confidence.MEDIUM if confidence > 0.5
            else Confidence.LOW
        )

        key_points = [summary[:300]]
        if "factors" in raw and isinstance(raw["factors"], dict):
            for name, score in list(raw["factors"].items())[:5]:
                key_points.append(f"{name}: {score}")

        return AnalystReport(
            agent_name="vibe_trading_factor",
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            conviction_level=conviction,
            key_points=key_points,
            risks=["Factor signals are historical and may decay"],
            timeframe="1d",
            evidence={"raw": raw},
            reasoning=summary,
        )

    async def alpha_zoo_evidence(
        self,
        symbol: str,
        alpha_names: Optional[List[str]] = None,
    ) -> List[EvidenceItem]:
        """Convert Alpha Zoo benchmark results into EvidenceItems."""
        raw = await self.alpha_zoo(symbol, alpha_names=alpha_names)
        if raw is None:
            return []

        alphas = raw.get("alphas", raw.get("results", []))
        if not isinstance(alphas, list):
            alphas = [alphas]

        evidence: List[EvidenceItem] = []
        for alpha in alphas[:20]:
            if not isinstance(alpha, dict):
                continue
            name = alpha.get("name", alpha.get("alpha", "unknown"))
            ic = alpha.get("ic", alpha.get("score", 0))
            snippet = f"Alpha {name}: IC={ic}"
            evidence.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"mcp://vibe-trading/alpha_zoo/{symbol}/{name}",
                    title=f"Alpha Zoo: {name}",
                    snippet=snippet[:300],
                    timestamp=datetime.utcnow(),
                    confidence=min(0.95, float(ic) if isinstance(ic, (int, float)) else 0.5),
                    tags=["vibe_trading", "alpha_zoo", symbol, name],
                )
            )

        return evidence

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(data: Any) -> str:
        """Best-effort text extraction from Vibe-Trading output."""
        if isinstance(data, str):
            return data
        if not isinstance(data, dict):
            return str(data)
        for key in ("summary", "analysis", "result", "message", "description"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return str(data)[:500]
