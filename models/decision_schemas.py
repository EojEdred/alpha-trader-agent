"""Structured Decision Schemas — Pydantic models for all agent decisions."""

from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Verdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    HOLD = "hold"
    ESCALATE = "escalate"


class AnalystReport(BaseModel):
    """Output from any analyst (technical, sentiment, news, fundamental)."""

    agent_name: str = Field(description="Name of the analyst agent")
    symbol: str = Field(description="Ticker symbol analyzed")
    direction: Direction = Field(description="Bullish, bearish, or neutral")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score 0-1")
    conviction_level: Confidence = Field(description="Human-readable confidence level")
    key_points: List[str] = Field(description="Top 3-5 bullet points supporting the conclusion")
    risks: List[str] = Field(description="Key risks that could invalidate the thesis")
    timeframe: str = Field(description="Expected holding period")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Structured evidence")
    reasoning: str = Field(description="Natural language explanation of the analysis")


class ResearchPlan(BaseModel):
    """Research Manager synthesizes all analyst reports into an investment plan."""

    symbol: str = Field(description="Ticker symbol")
    recommendation: Direction = Field(description="Overall directional recommendation")
    confidence: float = Field(ge=0.0, le=1.0, description="Aggregate confidence")
    conviction_level: Confidence = Field(description="Human-readable confidence")
    analyst_agreement: str = Field(description="E.g., '3/4 analysts bullish, 1 neutral'")
    rationale: str = Field(description="Summary of debate: which arguments won")
    strategic_actions: str = Field(description="Concrete steps for the trader")
    divergent_views: List[str] = Field(description="Arguments from the losing side")
    reports_considered: List[str] = Field(description="Names of analysts whose reports were read")


class TradeProposal(BaseModel):
    """Trader converts research plan into a concrete order."""

    symbol: str = Field(description="Ticker symbol")
    action: Direction = Field(description="long / short / neutral (hold)")
    entry_price: float = Field(description="Proposed entry price")
    stop_loss: float = Field(description="Hard stop loss price")
    take_profit: float = Field(description="Profit target price")
    position_size: int = Field(description="Number of shares/contracts")
    risk_amount: float = Field(description="Dollar risk on this trade")
    risk_reward_ratio: float = Field(description="R:R ratio")
    rationale: str = Field(description="Why this entry/stop/target was chosen")
    time_horizon: str = Field(description="Expected hold time")
    venue: str = Field(description="Where to execute")
    order_type: str = Field(default="MARKET", description="MARKET or LIMIT")


class RiskAssessment(BaseModel):
    """Risk Manager evaluates the trade proposal before execution."""

    symbol: str = Field(description="Ticker symbol")
    verdict: Verdict = Field(description="approve, reject, hold, or escalate")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in verdict")
    concerns: List[str] = Field(description="Specific risk concerns identified")
    mitigations: List[str] = Field(description="Suggested risk mitigations")
    max_position_size: Optional[int] = Field(None, description="Recommended max size if approving")
    max_loss_pct: Optional[float] = Field(None, description="Max account % at risk")
    correlated_exposure: List[str] = Field(default_factory=list, description="Other positions with correlation risk")
    reasoning: str = Field(description="Natural language risk analysis")


class FinalDecision(BaseModel):
    """Portfolio Manager's final approve/reject with any modifications."""

    symbol: str = Field(description="Ticker symbol")
    verdict: Verdict = Field(description="Final decision")
    approved_size: Optional[int] = Field(None, description="Approved position size")
    approved_entry: Optional[float] = Field(None, description="Approved entry price")
    approved_stop: Optional[float] = Field(None, description="Approved stop price")
    approved_target: Optional[float] = Field(None, description="Approved target price")
    reasoning: str = Field(description="Why the decision was made")
    execution_venue: Optional[str] = Field(None, description="Where to execute")
    timestamp: str = Field(description="ISO timestamp of decision")
