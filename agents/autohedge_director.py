"""
AutoHedge Director — Alpha Trader native implementation

Re-implements AutoHedge's four-agent pipeline (Director → Quant → Risk → Execution)
using Alpha Trader's own analysts and risk governor. This avoids relying on the
`autohedge` package's LLM handoffs and produces structured TradeIntents that the
rest of the system can execute.

Usage:
    from agents.autohedge_director import AutoHedgeDirector

    director = AutoHedgeDirector(config)
    result = await director.run_cycle("AAPL", task="Hedge AAPL long with QQQ short")
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from agents.base_analyst import BaseAnalyst
from models import ExecutionMode, TradeIntent, TradeStatus, generate_intent_id
from models.decision_schemas import AnalystReport, Confidence, Direction
from tools.risk_governor import RiskGovernor
from tools.signal_feed import record_autohedge_signals


try:
    from agents.flow_analyst import FlowAnalyst
except ImportError:
    FlowAnalyst = None  # type: ignore

try:
    from agents.massive_analyst import MassiveAnalyst
except ImportError:
    MassiveAnalyst = None  # type: ignore

try:
    from agents.quant_analyst import QuantAnalyst
except ImportError:
    QuantAnalyst = None  # type: ignore

try:
    from agents.technical_analyst import TechnicalAnalyst
except ImportError:
    TechnicalAnalyst = None  # type: ignore

try:
    from tools.llm_factory import KimiCLIWrapper
except ImportError:
    KimiCLIWrapper = None  # type: ignore


class AutoHedgeDirector(BaseAnalyst):
    """Multi-agent hedge-fund director implemented with Alpha Trader primitives."""

    name = "autohedge_director"
    description = "Replicates AutoHedge's Director/Quant/Risk/Execution pipeline"
    default_weight = 0.9

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.risk_governor = RiskGovernor(self.config)
        self._llm = None

    def _get_llm(self):
        if self._llm is None and KimiCLIWrapper is not None:
            self._llm = KimiCLIWrapper(temperature=0.2)
        return self._llm

    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """Satisfy BaseAnalyst interface — runs a single-symbol hedge cycle."""
        result = await self.run_cycle(symbol)
        top = result.get("recommendations", [{}])[0]
        return AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=Direction(top.get("direction", "neutral")),
            confidence=top.get("confidence", 0.5),
            conviction_level=Confidence.HIGH if top.get("confidence", 0) > 0.8 else Confidence.MEDIUM if top.get("confidence", 0) > 0.5 else Confidence.LOW,
            key_points=[result.get("thesis", "")[:300]],
            risks=[d.get("rejection_reason", "") for d in result.get("risk_decisions", []) if not d.get("approved")],
            timeframe="swing",
            evidence={"autohedge_cycle": result},
            reasoning=result.get("thesis", "AutoHedge director cycle"),
        )

    async def run_cycle(
        self,
        symbol_or_task: str,
        task: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Run the full Director → Quant → Risk → Execution cycle.

        Args:
            symbol_or_task: Primary symbol (e.g. "AAPL") or raw task string.
            task: Optional explicit task. If omitted, derived from symbol.

        Returns:
            Dict with thesis, reports, risk_decisions, recommendations, intents.
        """
        symbols = self._extract_symbols(symbol_or_task)
        primary_symbol = symbols[0] if symbols else symbol_or_task.upper()
        task = task or f"Analyze {primary_symbol} and produce a hedged trade recommendation"

        logger.info(f"AutoHedgeDirector: starting cycle for {primary_symbol}")

        # 1. Director: generate thesis
        thesis = await self._director_thesis(task, primary_symbol)

        # 2. Quant: gather analyst reports
        reports = await self._quant_analysis(primary_symbol)

        # 3. Risk: build intent and validate
        intent = self._build_intent(primary_symbol, thesis, reports)
        risk_decision = await self.risk_governor.validate(intent)

        # 4. Execution: finalize recommendation
        recommendation = {
            "symbol": primary_symbol,
            "direction": intent.direction,
            "entry_price": intent.entry_price,
            "stop_loss": intent.stop_price,
            "take_profit": intent.target_price,
            "size": intent.size,
            "confidence": intent.conviction,
            "risk_approved": risk_decision.approved,
            "risk_reason": risk_decision.rejection_reason,
            "thesis": thesis,
        }

        result = {
            "task": task,
            "primary_symbol": primary_symbol,
            "thesis": thesis,
            "reports": [r.model_dump() for r in reports],
            "risk_decisions": [risk_decision.to_dict()],
            "recommendations": [recommendation],
            "intents": [intent.to_dict()] if risk_decision.approved else [],
            "generated_at": datetime.utcnow().isoformat(),
        }

        try:
            await record_autohedge_signals(result)
        except Exception as e:
            logger.warning(f"AutoHedgeDirector: failed to record signals: {e}")

        return result

    async def _director_thesis(self, task: str, symbol: str) -> str:
        """Use LLM to generate a concise thesis."""
        llm = self._get_llm()
        if llm is None:
            return f"No LLM available; directional thesis for {symbol} based on quant reports."

        prompt = (
            f"You are the Director of an AI hedge fund. Task: {task}\n"
            f"Primary symbol: {symbol}.\n"
            f"Provide a 2-3 sentence directional thesis (bullish/bearish/neutral) "
            f"and the key risk to watch. Be concise."
        )
        try:
            from browser_use.llm.messages import UserMessage

            response = await llm.ainvoke([UserMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
            return content.strip()
        except Exception as e:
            logger.warning(f"AutoHedgeDirector LLM thesis failed: {e}")
            return f"Thesis generation failed; using quant signals for {symbol}."

    async def _quant_analysis(self, symbol: str) -> List[AnalystReport]:
        """Run all available Alpha Trader analysts on the symbol."""
        analysts: List[BaseAnalyst] = []
        if TechnicalAnalyst is not None:
            analysts.append(TechnicalAnalyst(self.config))
        if MassiveAnalyst is not None:
            analysts.append(MassiveAnalyst(self.config))
        if QuantAnalyst is not None:
            analysts.append(QuantAnalyst(self.config))
        if FlowAnalyst is not None:
            analysts.append(FlowAnalyst(self.config))

        reports: List[AnalystReport] = []
        results = await asyncio.gather(
            *[self._safe_analyze(a, symbol) for a in analysts],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, AnalystReport):
                reports.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"AutoHedgeDirector analyst failed: {result}")
        return reports

    @staticmethod
    async def _safe_analyze(analyst: BaseAnalyst, symbol: str) -> AnalystReport:
        return await analyst.analyze(symbol)

    def _build_intent(self, symbol: str, thesis: str, reports: List[AnalystReport]) -> TradeIntent:
        """Aggregate analyst reports into a TradeIntent."""
        # Directional vote weighted by confidence
        long_weight = sum(
            r.confidence * BaseAnalyst.get_weight(self.config)
            for r in reports if r.direction == Direction.LONG
        )
        short_weight = sum(
            r.confidence * BaseAnalyst.get_weight(self.config)
            for r in reports if r.direction == Direction.SHORT
        )

        if long_weight > short_weight:
            direction = "long"
            confidence = min(0.95, 0.5 + long_weight)
        elif short_weight > long_weight:
            direction = "short"
            confidence = min(0.95, 0.5 + short_weight)
        else:
            direction = "neutral"
            confidence = 0.45

        # Estimate prices from reports or use placeholders
        entry = 100.0
        for r in reports:
            evidence = r.evidence or {}
            if "current_price" in evidence and evidence["current_price"]:
                entry = float(evidence["current_price"])
                break
            snapshot = evidence.get("snapshot", {})
            day = snapshot.get("day", {})
            if "c" in day:
                entry = float(day["c"])
                break

        stop = entry * (0.97 if direction == "long" else 1.03)
        target = entry * (1.06 if direction == "long" else 0.94)
        size = 10

        return TradeIntent(
            id=generate_intent_id(),
            capsule_id="autohedge_director",
            thesis_id="autohedge_director",
            symbol=symbol,
            direction=direction,
            entry_price=round(entry, 2),
            stop_price=round(stop, 2),
            target_price=round(target, 2),
            conviction=round(confidence, 2),
            invalidation_price=round(stop, 2),
            time_stop=datetime.utcnow() + timedelta(days=7),
            risk_reward_ratio=round(abs((target - entry) / (entry - stop)), 2) if entry != stop else 1.0,
            size=size,
            execution_mode=ExecutionMode.CONFIRM,
            venue="auto",
            evidence_citations=[r.agent_name for r in reports],
            tags=["autohedge_director"],
        )

    @staticmethod
    def _extract_symbols(text: str) -> List[str]:
        """Extract likely ticker symbols from task text."""
        symbols = re.findall(r"\b[A-Z]{1,5}\b", text)
        ignore = {"A", "I", "US", "USD", "ETF", "NYSE", "NASDAQ", "CEO", "CFO", "AI"}
        return [s for s in symbols if s not in ignore]
