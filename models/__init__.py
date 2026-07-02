"""
Zynth-Level Data Models

Defines core schemas for the upgraded Dexter platform:
- EvidenceItem: Single piece of evidence with citation
- ThesisObject: Synthesized thesis from evidence
- TradeIntent: Trade recommendation from capsules
- RiskDecision: Risk governor's verdict
- ExecutionPlan: Final execution plan
- ExecutionResult: Result of execution attempt

All models are JSON-serializable and stored in audit DB.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from loguru import logger


class RegimeBias(str, Enum):
    """Regime bias for thesis."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"


class ExecutionMode(str, Enum):
    """Execution mode for trade intents."""

    AUTO = "auto"
    CONFIRM = "confirm"
    SIGNAL_ONLY = "signal_only"


class ExecutionMethod(str, Enum):
    """Execution method used to place order."""
    
    API = "api"
    BROWSER = "browser"
    DESKTOP = "desktop"
    SIGNAL_ONLY = "signal_only"


class TradeStatus(str, Enum):
    """Status of a trade intent."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CLOSED = "cancelled"


@dataclass
class EvidenceItem:
    """Single piece of evidence with citation."""

    id: str
    url: str
    title: str
    snippet: str
    timestamp: datetime
    confidence: float  # 0.0-1.0 reliability score
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        """Create from dict (from DB)."""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)


@dataclass
class ThesisObject:
    """Synthesized thesis from evidence."""

    id: str
    summary: str
    evidence_ids: List[str]
    conviction: float  # 0.0-1.0 overall conviction
    regime_bias: RegimeBias
    created_at: datetime
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        d["regime_bias"] = self.regime_bias.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThesisObject":
        """Create from dict (from DB)."""
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("regime_bias"), str):
            data["regime_bias"] = RegimeBias(data["regime_bias"])
        return cls(**data)


@dataclass
class TradeIntent:
    """Trade recommendation from a capsule."""

    id: str
    capsule_id: str  # Which capsule generated this
    thesis_id: str  # Which thesis this supports
    symbol: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_price: float
    target_price: float
    conviction: float  # 0.0-1.0
    invalidation_price: float  # Price that invalidates thesis
    time_stop: datetime  # Max hold time
    risk_reward_ratio: float
    size: Optional[float] = None  # Set by PortfolioBrain
    execution_mode: ExecutionMode = ExecutionMode.SIGNAL_ONLY
    venue: str = "auto"  # "oanda", "kalshi", "polymarket", etc.
    evidence_citations: List[str] = field(default_factory=list)
    status: TradeStatus = TradeStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["time_stop"] = self.time_stop.isoformat()
        d["created_at"] = self.created_at.isoformat()
        d["execution_mode"] = self.execution_mode.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TradeIntent":
        """Create from dict (from DB)."""
        if isinstance(data.get("time_stop"), str):
            data["time_stop"] = datetime.fromisoformat(data["time_stop"])
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("execution_mode"), str):
            data["execution_mode"] = ExecutionMode(data["execution_mode"])
        if isinstance(data.get("status"), str):
            data["status"] = TradeStatus(data["status"])
        return cls(**data)


@dataclass
class RiskDecision:
    """Risk governor's verdict on a trade intent."""

    intent_id: str
    approved: bool
    rejection_reason: Optional[str] = None
    risk_adjusted_size: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["checked_at"] = self.checked_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RiskDecision":
        """Create from dict (from DB)."""
        if isinstance(data.get("checked_at"), str):
            data["checked_at"] = datetime.fromisoformat(data["checked_at"])
        return cls(**data)


@dataclass
class ExecutionPlan:
    """Final execution plan ready for submission."""

    intent_id: str
    order_payload: Dict[str, Any]  # Full order parameters for broker
    execution_mode: ExecutionMode
    venue: str
    requires_confirmation: bool
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"  # "pending", "submitted", "filled", "cancelled"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        d["execution_mode"] = self.execution_mode.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPlan":
        """Create from dict (from DB)."""
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("execution_mode"), str):
            data["execution_mode"] = ExecutionMode(data["execution_mode"])
        return cls(**data)


@dataclass
class ExecutionResult:
    """Result of a trade execution attempt."""
    
    success: bool
    method: ExecutionMethod
    venue: str
    order_id: Optional[str] = None
    status: str = "unknown"
    fill_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["method"] = self.method.value if isinstance(self.method, ExecutionMethod) else self.method
        return d


# Helper functions for ID generation

def generate_evidence_id() -> str:
    """Generate unique evidence item ID."""
    return f"evd_{uuid.uuid4().hex[:16]}"


def generate_thesis_id() -> str:
    """Generate unique thesis object ID."""
    return f"ths_{uuid.uuid4().hex[:16]}"


def generate_intent_id() -> str:
    """Generate unique trade intent ID."""
    return f"int_{uuid.uuid4().hex[:16]}"


def generate_execution_plan_id() -> str:
    """Generate unique execution plan ID."""
    return f"exe_{uuid.uuid4().hex[:16]}"
