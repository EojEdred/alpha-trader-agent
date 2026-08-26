"""
Base Analyst Agent

All analyst agents inherit from BaseAnalyst and emit a standardized
AnalystReport. This lets the ResearchManager weight, compare, and synthesize
outputs from technical, flow, sentiment, and quant analysts uniformly.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from models.decision_schemas import AnalystReport


class BaseAnalyst(ABC):
    """Abstract base class for analyst agents."""

    name: str = "base_analyst"
    description: str = "Base analyst agent"

    # Default weight in ResearchManager synthesis. Subclasses can override.
    default_weight: float = 1.0

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    async def analyze(
        self,
        symbol: str,
        price_data: Optional[Dict[str, Any]] = None,
    ) -> AnalystReport:
        """
        Analyze a symbol and return an AnalystReport.

        Args:
            symbol: Ticker symbol.
            price_data: Optional current price/quote data.

        Returns:
            AnalystReport with direction, confidence, key points, and risks.
        """
        ...

    @classmethod
    def get_weight(cls, config: Optional[Dict[str, Any]] = None) -> float:
        """
        Get analyst weight from config or class default.

        Config path: analyst_weights.<agent_name>
        """
        if config:
            weights = config.get("analyst_weights", {})
            return float(weights.get(cls.name, cls.default_weight))
        return cls.default_weight
