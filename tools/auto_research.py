"""
Auto-Research Engine for Alpha Trader

Nightly/scheduled research orchestrator that:
1. Scans configured watchlists
2. Pulls TradingView TA, Unusual Whales flow/GEX, and Massive market data
3. Synthesizes analyst reports into ResearchPlans via ResearchManager
4. Persists everything to MemoryLog
5. Emits a markdown research agenda for the next session

Usage:
    from tools.auto_research import AutoResearchEngine

    engine = AutoResearchEngine(config)
    agenda = await engine.run_cycle(symbols=["SPY", "QQQ", "AAPL"])
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from models import EvidenceItem, ThesisObject, generate_evidence_id, generate_thesis_id
from models.decision_schemas import AnalystReport, ResearchPlan
from tools.memory_log import MemoryLog
from tools.signal_feed import record_plan_signals
from agents.massive_analyst import MassiveAnalyst
from agents.valuecell_analyst import ValueCellAnalyst
from tools.tradingview_mcp import TradingViewMCP
from tools.unusual_whales import UnusualWhalesClient


class AutoResearchEngine:
    """
    Automated research cycle that mirrors Alpha Trader's 5-phase pipeline
    but runs unattended to pre-build the morning research agenda.
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        tv_mcp: Optional[TradingViewMCP] = None,
        uw_client: Optional[UnusualWhalesClient] = None,
        massive_analyst: Optional[MassiveAnalyst] = None,
        valuecell_analyst: Optional[ValueCellAnalyst] = None,
        memory_log: Optional[MemoryLog] = None,
    ):
        self.config = config or {}
        self.tv = tv_mcp or TradingViewMCP(self.config)
        self.uw = uw_client or UnusualWhalesClient(self.config)
        self.massive = massive_analyst or MassiveAnalyst(self.config)
        self.valuecell = valuecell_analyst or ValueCellAnalyst(self.config)
        self.memory = memory_log or MemoryLog()

        auto_config = self.config.get("auto_research", {})
        self.max_symbols_per_cycle = auto_config.get("max_symbols_per_cycle", 50)
        self.confidence_threshold = auto_config.get("confidence_threshold", 0.6)
        self.save_evidence = auto_config.get("save_evidence", True)
        self.output_dir = Path(auto_config.get("output_dir", "data/research"))
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def run_cycle(
        self,
        symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run a full auto-research cycle.

        Args:
            symbols: Explicit list of symbols. If None, uses watchlists.

        Returns:
            {
                "generated_at": ISO timestamp,
                "symbols": [...],
                "evidence_count": int,
                "plans": [ResearchPlan, ...],
                "thesis": ThesisObject,
                "report_path": str,
                "summary": str,
            }
        """
        symbols = self._resolve_symbols(symbols)
        logger.info(f"AutoResearchEngine: starting cycle for {len(symbols)} symbols")

        # Gather evidence and reports for all symbols in parallel
        results = await asyncio.gather(
            *[self._research_symbol(sym) for sym in symbols[: self.max_symbols_per_cycle]],
            return_exceptions=True,
        )

        all_evidence: List[EvidenceItem] = []
        all_reports: List[AnalystReport] = []
        for sym, result in zip(symbols, results):
            if isinstance(result, Exception):
                logger.error(f"AutoResearchEngine: failed researching {sym}: {result}")
                continue
            evidence, reports = result
            all_evidence.extend(evidence)
            all_reports.extend(reports)

        logger.info(
            f"AutoResearchEngine: gathered {len(all_evidence)} evidence items, "
            f"{len(all_reports)} analyst reports"
        )

        # Synthesize a thesis from all evidence
        thesis = await self._synthesize_thesis(all_evidence)

        # Synthesize per-symbol ResearchPlans
        plans = await self._synthesize_plans(symbols, all_reports)

        # Publish copy-trade signals for high-confidence plans
        try:
            await record_plan_signals(plans, source="auto_research")
        except Exception as e:
            logger.warning(f"AutoResearchEngine: failed to record plan signals: {e}")

        # Persist
        if self.save_evidence:
            self._persist(all_evidence, all_reports, plans, thesis)

        # Generate report
        report_path = self._write_report(all_evidence, all_reports, plans, thesis)

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "symbols": symbols,
            "evidence_count": len(all_evidence),
            "plans": plans,
            "thesis": thesis,
            "report_path": str(report_path),
            "summary": self._build_summary(plans, thesis),
        }

    async def research_symbol(
        self,
        symbol: str,
    ) -> Tuple[List[EvidenceItem], List[AnalystReport]]:
        """Public helper to research a single symbol."""
        return await self._research_symbol(symbol)

    # ------------------------------------------------------------------
    # Internal research pipeline
    # ------------------------------------------------------------------

    async def _research_symbol(
        self,
        symbol: str,
    ) -> Tuple[List[EvidenceItem], List[AnalystReport]]:
        """Gather all evidence and analyst reports for one symbol."""
        evidence: List[EvidenceItem] = []
        reports: List[AnalystReport] = []

        # 1. TradingView technical analysis
        tv_reports = await asyncio.gather(
            self.tv.analyze_symbol(symbol, exchange="NASDAQ", timeframe="1d"),
            self.tv.analyze_multi_timeframe(symbol, exchange="NASDAQ"),
            self.tv.multi_agent_debate(symbol, exchange="NASDAQ", timeframe="1d"),
            return_exceptions=True,
        )
        for report in tv_reports:
            if isinstance(report, Exception):
                logger.warning(f"TradingView report failed for {symbol}: {report}")
                continue
            reports.append(report)
            evidence.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"mcp://tradingview/{symbol}",
                    title=f"TradingView: {symbol} ({report.agent_name})",
                    snippet=report.reasoning[:400],
                    timestamp=datetime.utcnow(),
                    confidence=report.confidence,
                    tags=["tradingview", symbol, report.agent_name],
                )
            )

        # 2. TradingView market scan evidence (symbol-specific)
        try:
            scan_evidence = await self.tv.scan_market("bollinger_breakout")
            evidence.extend([e for e in scan_evidence if symbol in e.tags])
        except Exception as e:
            logger.warning(f"TradingView scan failed for {symbol}: {e}")

        # 3. Unusual Whales options flow
        try:
            flow_evidence = await self.uw.flow_evidence(symbol=symbol, limit=20)
            evidence.extend(flow_evidence)
        except Exception as e:
            logger.warning(f"UW flow failed for {symbol}: {e}")

        # 4. Unusual Whales GEX
        try:
            gex_report = await self.uw.gex_analyst_report(symbol)
            reports.append(gex_report)
            evidence.append(
                EvidenceItem(
                    id=generate_evidence_id(),
                    url=f"https://unusualwhales.com/gex/{symbol}",
                    title=f"UW GEX: {symbol}",
                    snippet=gex_report.reasoning[:400],
                    timestamp=datetime.utcnow(),
                    confidence=gex_report.confidence,
                    tags=["unusual_whales", "gex", symbol],
                )
            )
        except Exception as e:
            logger.warning(f"UW GEX failed for {symbol}: {e}")

        # 5. Unusual Whales dark pool
        try:
            dp_evidence = await self.uw.dark_pool_evidence(symbol=symbol, limit=10)
            evidence.extend(dp_evidence)
        except Exception as e:
            logger.warning(f"UW dark pool failed for {symbol}: {e}")

        # 6. Massive API market-data + news
        try:
            massive_report = await self.massive.analyze(symbol)
            if massive_report.confidence > 0:
                reports.append(massive_report)
                evidence.append(
                    EvidenceItem(
                        id=generate_evidence_id(),
                        url=f"https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}",
                        title=f"Massive: {symbol} ({massive_report.direction.value})",
                        snippet=massive_report.reasoning[:400],
                        timestamp=datetime.utcnow(),
                        confidence=massive_report.confidence,
                        tags=["massive", symbol, massive_report.direction.value],
                    )
                )
        except Exception as e:
            logger.warning(f"Massive analyst failed for {symbol}: {e}")

        try:
            massive_evidence = await self.massive.evidence_for_symbol(symbol)
            evidence.extend(massive_evidence)
        except Exception as e:
            logger.warning(f"Massive evidence failed for {symbol}: {e}")

        # 7. ValueCell fundamental / news / strategy
        try:
            vc_report = await self.valuecell.analyze(symbol)
            if vc_report.confidence > 0:
                reports.append(vc_report)
                evidence.append(
                    EvidenceItem(
                        id=generate_evidence_id(),
                        url=f"valuecell://{symbol}",
                        title=f"ValueCell: {symbol} ({vc_report.direction.value})",
                        snippet=vc_report.reasoning[:400],
                        timestamp=datetime.utcnow(),
                        confidence=vc_report.confidence,
                        tags=["valuecell", symbol, vc_report.direction.value],
                    )
                )
        except Exception as e:
            logger.warning(f"ValueCell analyst failed for {symbol}: {e}")

        try:
            vc_evidence = await self.valuecell.evidence_for_symbol(symbol)
            evidence.extend(vc_evidence)
        except Exception as e:
            logger.warning(f"ValueCell evidence failed for {symbol}: {e}")

        return evidence, reports

    async def _synthesize_thesis(self, evidence: List[EvidenceItem]) -> ThesisObject:
        """Create a ThesisObject from all gathered evidence."""
        if not evidence:
            return ThesisObject(
                id=generate_thesis_id(),
                summary="No evidence gathered during auto-research cycle",
                evidence_ids=[],
                conviction=0.0,
                regime_bias="neutral",
                created_at=datetime.utcnow(),
                tags=["auto_research", "empty"],
            )

        # Weighted average confidence, with higher weight for TradingView reports
        confidences = [e.confidence for e in evidence]
        avg_confidence = sum(confidences) / len(confidences)

        # Regime bias heuristic: count bullish/bearish snippets
        bullish = sum(1 for e in evidence if any(k in e.snippet.lower() for k in ("bull", "buy", "long", "upside")))
        bearish = sum(1 for e in evidence if any(k in e.snippet.lower() for k in ("bear", "sell", "short", "downside")))

        if bullish > bearish * 1.2:
            regime = "risk_on"
        elif bearish > bullish * 1.2:
            regime = "risk_off"
        else:
            regime = "neutral"

        summaries = [f"{e.title}: {e.snippet[:120]}" for e in sorted(evidence, key=lambda x: x.confidence, reverse=True)[:10]]

        return ThesisObject(
            id=generate_thesis_id(),
            summary=" | ".join(summaries),
            evidence_ids=[e.id for e in evidence],
            conviction=avg_confidence,
            regime_bias=regime,
            created_at=datetime.utcnow(),
            tags=["auto_research", regime],
        )

    async def _synthesize_plans(
        self,
        symbols: List[str],
        reports: List[AnalystReport],
    ) -> List[ResearchPlan]:
        """Use ResearchManager to create one ResearchPlan per symbol."""
        from agents.research_manager import ResearchManager

        rm = ResearchManager()
        plans: List[ResearchPlan] = []

        symbol_reports: Dict[str, List[AnalystReport]] = {}
        for report in reports:
            symbol_reports.setdefault(report.symbol, []).append(report)

        for symbol in symbols:
            symbol_reps = symbol_reports.get(symbol, [])
            if not symbol_reps:
                continue
            try:
                plan = await rm.synthesize(symbol, symbol_reps)
                if plan.confidence >= self.confidence_threshold:
                    plans.append(plan)
            except Exception as e:
                logger.error(f"ResearchManager synthesis failed for {symbol}: {e}")

        # Sort by confidence descending
        plans.sort(key=lambda p: p.confidence, reverse=True)
        return plans

    # ------------------------------------------------------------------
    # Persistence and reporting
    # ------------------------------------------------------------------

    def _persist(
        self,
        evidence: List[EvidenceItem],
        reports: List[AnalystReport],
        plans: List[ResearchPlan],
        thesis: ThesisObject,
    ):
        """Persist evidence, reports, and plans to MemoryLog."""
        for report in reports:
            try:
                self.memory.record_analyst_report(report)
            except Exception as e:
                logger.debug(f"Failed to persist analyst report: {e}")

        for plan in plans:
            try:
                self.memory.record_research_plan(plan)
            except Exception as e:
                logger.debug(f"Failed to persist research plan: {e}")

    def _write_report(
        self,
        evidence: List[EvidenceItem],
        reports: List[AnalystReport],
        plans: List[ResearchPlan],
        thesis: ThesisObject,
    ) -> Path:
        """Write a markdown research agenda to disk."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = self.output_dir / f"research_agenda_{timestamp}.md"

        lines = [
            "# Auto-Research Agenda",
            f"Generated: {datetime.utcnow().isoformat()} UTC",
            "",
            "## Macro Thesis",
            f"- Regime: {thesis.regime_bias}",
            f"- Conviction: {thesis.conviction:.2%}",
            f"- Summary: {thesis.summary[:500]}",
            "",
            "## Top Research Plans",
        ]

        for i, plan in enumerate(plans[:15], 1):
            lines.extend([
                f"### {i}. {plan.symbol} — {plan.recommendation.value.upper()} ({plan.confidence:.0%})",
                f"- Rationale: {plan.rationale}",
                f"- Strategic Actions: {plan.strategic_actions}",
                f"- Analyst Agreement: {plan.analyst_agreement}",
                "",
            ])

        lines.extend([
            "## Evidence Summary",
            f"- Total evidence items: {len(evidence)}",
            "",
            "### By Source",
        ])

        source_counts: Dict[str, int] = {}
        for e in evidence:
            source = e.tags[0] if e.tags else "unknown"
            source_counts[source] = source_counts.get(source, 0) + 1
        for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {source}: {count}")

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"AutoResearchEngine: report written to {path}")
        return path

    def _build_summary(self, plans: List[ResearchPlan], thesis: ThesisObject) -> str:
        """One-line summary of the cycle output."""
        longs = sum(1 for p in plans if p.recommendation.value == "long")
        shorts = sum(1 for p in plans if p.recommendation.value == "short")
        return (
            f"Regime: {thesis.regime_bias}, "
            f"{len(plans)} actionable plans "
            f"({longs} long, {shorts} short, "
            f"{len(plans) - longs - shorts} neutral)"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_symbols(self, symbols: Optional[List[str]]) -> List[str]:
        """Resolve symbols from argument or watchlists."""
        if symbols:
            return list(dict.fromkeys(symbols))  # preserve order, dedupe

        watchlists = self.config.get("watchlists", {})
        all_symbols: List[str] = []
        for category in ("options", "futures", "forex", "crypto"):
            all_symbols.extend(watchlists.get(category, []))

        # Normalize forex/crypto pairs to a symbol-friendly format
        normalized = []
        for sym in all_symbols:
            s = sym.replace("/", "").replace("-", "")
            normalized.append(s)

        return list(dict.fromkeys(normalized))
