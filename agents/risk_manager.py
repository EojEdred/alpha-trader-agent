"""
Risk Manager Agent

Evaluates trade proposals before execution. Challenges the trade from a risk
perspective and can approve, reject, hold, or escalate.

Inspired by TradingAgents' Risk Management team.

Usage:
    from agents.risk_manager import RiskManager

    rm = RiskManager()
    assessment = await rm.assess(proposal, research_plan, portfolio_state)
    if assessment.verdict == Verdict.APPROVE:
        execute_trade(proposal)
"""

import re
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger

from models.decision_schemas import (
    TradeProposal, ResearchPlan, RiskAssessment, FinalDecision,
    Verdict, Direction, Confidence,
)
from tools.llm_factory import LLMFactory


class RiskManager:
    """
    LLM-powered risk manager that debates trade proposals before execution.
    """

    name = "risk_manager"
    description = "Evaluates trade proposals for risk before execution"

    def __init__(self, model_name: str = "kimi-k2"):
        self.model_name = model_name
        self._llm = None

    def _get_llm(self):
        """Lazy-load LLM. Uses Kimi CLI wrapper for reliability on text tasks."""
        if self._llm is None:
            from tools.llm_factory import KimiCLIWrapper
            self._llm = KimiCLIWrapper(temperature=0.1)
        return self._llm

    async def assess(
        self,
        proposal: TradeProposal,
        research_plan: ResearchPlan,
        portfolio_state: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        """
        Assess a trade proposal and return a risk verdict.

        Args:
            proposal: The trade proposal from the Trader agent
            research_plan: The research plan that led to this trade
            portfolio_state: Current positions, P&L, exposure, etc.

        Returns:
            RiskAssessment with verdict and concerns
        """
        prompt = self._build_prompt(proposal, research_plan, portfolio_state)

        try:
            llm = self._get_llm()
            from browser_use.llm.messages import UserMessage

            response = await llm.ainvoke([UserMessage(content=prompt)])
            content = self._extract_content(response)

            assessment = self._parse_response(proposal.symbol, content)
            logger.info(
                f"RiskManager: {proposal.symbol} -> {assessment.verdict.value} "
                f"(confidence: {assessment.confidence:.0%})"
            )
            return assessment

        except Exception as e:
            logger.error(f"RiskManager LLM failed for {proposal.symbol}: {e}")
            return self._fallback_assessment(proposal, portfolio_state)

    @staticmethod
    def _extract_content(response) -> str:
        """Extract text content from various LLM response formats."""
        if hasattr(response, "completion") and response.completion:
            if isinstance(response.completion, str):
                return response.completion
        if hasattr(response, "content") and response.content:
            return response.content
        return str(response)

    def _build_prompt(
        self,
        proposal: TradeProposal,
        research_plan: ResearchPlan,
        portfolio_state: Optional[Dict[str, Any]],
    ) -> str:
        """Build the risk assessment prompt."""
        lines = [
            "You are the Risk Manager for a trading desk. Your job is to challenge every trade proposal and protect the firm's capital.",
            "",
            "=== TRADE PROPOSAL ===",
            f"Symbol: {proposal.symbol}",
            f"Action: {proposal.action.value.upper()}",
            f"Entry: ${proposal.entry_price:.2f}",
            f"Stop Loss: ${proposal.stop_loss:.2f}",
            f"Take Profit: ${proposal.take_profit:.2f}",
            f"Position Size: {proposal.position_size} units",
            f"Risk Amount: ${proposal.risk_amount:.2f}",
            f"Risk:Reward Ratio: {proposal.risk_reward_ratio:.1f}:1",
            f"Venue: {proposal.venue}",
            f"Time Horizon: {proposal.time_horizon}",
            f"Rationale: {proposal.rationale}",
            "",
            "=== RESEARCH PLAN ===",
            f"Recommendation: {research_plan.recommendation.value.upper()}",
            f"Confidence: {research_plan.confidence:.0%}",
            f"Analyst Agreement: {research_plan.analyst_agreement}",
            f"Rationale: {research_plan.rationale}",
            "",
        ]

        if portfolio_state:
            lines.extend([
                "=== PORTFOLIO STATE ===",
                f"Account Equity: ${portfolio_state.get('equity', 'N/A')}",
                f"Open Positions: {portfolio_state.get('open_positions', 'N/A')}",
                f"Day P&L: ${portfolio_state.get('day_pnl', 'N/A')}",
                f"Consecutive Losses: {portfolio_state.get('consecutive_losses', 0)}",
                f"Max Drawdown Today: {portfolio_state.get('max_drawdown_today', 'N/A')}%",
                "",
            ])

        lines.extend([
            "=== YOUR TASK ===",
            "",
            "Evaluate this trade from a risk perspective. Consider:",
            "1. Position sizing: Is the risk amount appropriate for the account?",
            "2. Stop loss: Is it too tight or too loose?",
            "3. Correlation: Are we already exposed to this sector/asset class?",
            "4. Market conditions: Is volatility too high? Any news events soon?",
            "5. Risk:Reward: Is the reward worth the risk?",
            "6. Consecutive losses: Should we reduce size after losses?",
            "",
            "Respond in this exact format:",
            "",
            "VERDICT: [Approve | Reject | Hold | Escalate]",
            "CONFIDENCE: [0.0 - 1.0]",
            "CONCERNS:",
            "- [Concern 1]",
            "- [Concern 2]",
            "MITIGATIONS:",
            "- [Mitigation 1]",
            "- [Mitigation 2]",
            "REASONING: [2-3 sentences explaining your risk assessment]",
            "",
        ])

        return "\n".join(lines)

    def _parse_response(self, symbol: str, content: str) -> RiskAssessment:
        """Parse LLM response into RiskAssessment."""
        verdict_match = re.search(r"VERDICT:\s*(\w+)", content, re.IGNORECASE)
        conf_match = re.search(r"CONFIDENCE:\s*(0\.\d+|1\.0|1|0)", content, re.IGNORECASE)

        verdict_str = (verdict_match.group(1).strip().lower() if verdict_match else "hold")
        confidence = float(conf_match.group(1)) if conf_match else 0.5

        # Map verdict
        verdict_map = {
            "approve": Verdict.APPROVE,
            "reject": Verdict.REJECT,
            "hold": Verdict.HOLD,
            "escalate": Verdict.ESCALATE,
        }
        verdict = verdict_map.get(verdict_str, Verdict.HOLD)

        # Extract concerns
        concerns = []
        concerns_section = re.search(r"CONCERNS:(.+?)(?:MITIGATIONS|REASONING|$)", content, re.IGNORECASE | re.DOTALL)
        if concerns_section:
            concerns = [line.strip("- ").strip() for line in concerns_section.group(1).strip().split("\n") if line.strip().startswith("-")]

        # Extract mitigations
        mitigations = []
        mitigations_section = re.search(r"MITIGATIONS:(.+?)(?:REASONING|$)", content, re.IGNORECASE | re.DOTALL)
        if mitigations_section:
            mitigations = [line.strip("- ").strip() for line in mitigations_section.group(1).strip().split("\n") if line.strip().startswith("-")]

        # Extract reasoning
        reasoning_match = re.search(r"REASONING:\s*(.+?)(?:\n\n|$)", content, re.IGNORECASE | re.DOTALL)
        reasoning = reasoning_match.group(1).strip() if reasoning_match else "No reasoning provided"

        return RiskAssessment(
            symbol=symbol,
            verdict=verdict,
            confidence=confidence,
            concerns=concerns,
            mitigations=mitigations,
            max_position_size=None,
            max_loss_pct=None,
            correlated_exposure=[],
            reasoning=reasoning,
        )

    def _fallback_assessment(self, proposal: TradeProposal, portfolio_state: Optional[Dict]) -> RiskAssessment:
        """Simple fallback when LLM fails."""
        concerns = []
        mitigations = []

        # Basic checks
        if proposal.risk_reward_ratio < 1.5:
            concerns.append(f"Risk:Reward ratio ({proposal.risk_reward_ratio:.1f}:1) below 1.5 minimum")
            mitigations.append("Wait for better setup or wider target")

        if portfolio_state:
            consecutive = portfolio_state.get("consecutive_losses", 0)
            if consecutive >= 3:
                concerns.append(f"Three consecutive losses ({consecutive}). Potential tilt risk.")
                mitigations.append("Reduce position size by 50% or pause trading")

        if not concerns:
            verdict = Verdict.APPROVE
            confidence = 0.6
        else:
            verdict = Verdict.HOLD
            confidence = 0.5

        return RiskAssessment(
            symbol=proposal.symbol,
            verdict=verdict,
            confidence=confidence,
            concerns=concerns,
            mitigations=mitigations,
            correlated_exposure=[],
            reasoning="Fallback risk assessment due to LLM failure. Basic checks applied.",
        )


class PortfolioManager:
    """
    Final decision maker. Takes Research Plan + Risk Assessment and produces
    the final execute/hold decision with approved sizing.
    """

    name = "portfolio_manager"
    description = "Final approve/reject with position sizing"

    def decide(
        self,
        research_plan: ResearchPlan,
        risk_assessment: RiskAssessment,
        proposal: TradeProposal,
    ) -> FinalDecision:
        """
        Make final decision based on research and risk assessment.
        """
        now = datetime.utcnow().isoformat()

        # If risk rejected or held, follow risk manager
        if risk_assessment.verdict == Verdict.REJECT:
            return FinalDecision(
                symbol=proposal.symbol,
                verdict=Verdict.REJECT,
                reasoning=f"Risk Manager rejected: {risk_assessment.reasoning}",
                timestamp=now,
            )

        if risk_assessment.verdict == Verdict.HOLD:
            return FinalDecision(
                symbol=proposal.symbol,
                verdict=Verdict.HOLD,
                reasoning=f"Risk Manager held: {risk_assessment.reasoning}",
                timestamp=now,
            )

        # If risk escalated, hold
        if risk_assessment.verdict == Verdict.ESCALATE:
            return FinalDecision(
                symbol=proposal.symbol,
                verdict=Verdict.HOLD,
                reasoning=f"Risk Manager escalated: {risk_assessment.reasoning}",
                timestamp=now,
            )

        # If research is neutral or low confidence, hold
        if research_plan.recommendation == Direction.NEUTRAL or research_plan.confidence < 0.5:
            return FinalDecision(
                symbol=proposal.symbol,
                verdict=Verdict.HOLD,
                reasoning=f"Research confidence too low ({research_plan.confidence:.0%}) or neutral recommendation",
                timestamp=now,
            )

        # Apply risk mitigations
        approved_size = proposal.position_size
        if risk_assessment.max_position_size:
            approved_size = min(approved_size, risk_assessment.max_position_size)

        # Apply size reduction after consecutive losses
        # (This would come from portfolio state in real usage)

        # Approve with potential modifications
        return FinalDecision(
            symbol=proposal.symbol,
            verdict=Verdict.APPROVE,
            approved_size=approved_size,
            approved_entry=proposal.entry_price,
            approved_stop=proposal.stop_loss,
            approved_target=proposal.take_profit,
            execution_venue=proposal.venue,
            reasoning=(
                f"APPROVED. Research: {research_plan.recommendation.value.upper()} "
                f"({research_plan.confidence:.0%} confidence). "
                f"Risk: {risk_assessment.verdict.value.upper()} "
                f"({risk_assessment.confidence:.0%} confidence). "
                f"R:R = {proposal.risk_reward_ratio:.1f}:1"
            ),
            timestamp=now,
        )
