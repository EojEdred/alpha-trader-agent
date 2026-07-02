"""
Strategy Capsules Package

Plugin-based strategy system for Dexter.
Each capsule implements BaseCapsule interface and generates TradeIntents.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime
from loguru import logger

from models import ThesisObject, TradeIntent, ExecutionMode


class BaseCapsule(ABC):
    """
    Base class for all strategy capsules.

    Each capsule:
    - Analyzes market data for specific symbols/timeframes
    - Generates TradeIntent objects based on thesis and technicals
    - Can be extended for new strategies without changing core code
    """

    def __init__(self, config: Dict[str, Any] = None):
        """
        Initialize capsule with optional configuration.

        Args:
            config: Optional configuration dict
        """
        self.config = config or {}

    @property
    @abstractmethod
    def capsule_id(self) -> str:
        """Unique capsule identifier (e.g., 'spy_qqq_liquidity_sweep')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable capsule name."""
        pass

    @property
    @abstractmethod
    def symbols(self) -> List[str]:
        """Symbols this capsule monitors."""
        pass

    @property
    @abstractmethod
    def execution_mode(self) -> ExecutionMode:
        """Default execution mode: AUTO, CONFIRM, or SIGNAL_ONLY."""
        pass

    @abstractmethod
    async def generate_intents(
        self, thesis: ThesisObject, market_data: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        """
        Generate trade intents based on thesis and market data.

        Args:
            thesis: ThesisObject with market bias and conviction
            market_data: Dict with market data (OHLCV, volume profile, order flow, etc.)
            **kwargs: Additional parameters (config, current prices, etc.)

        Returns:
            List of TradeIntent objects (0-2 per symbol typical)

        Notes:
            - Each intent must have unique ID
            - Must cite supporting evidence from thesis
            - Must include entry/exit criteria
            - Must set appropriate execution_mode
        """
        pass

    @abstractmethod
    async def validate_setup(self, symbol: str, current_price: float, **kwargs) -> bool:
        """
        Validate if setup meets entry criteria.

        Args:
            symbol: Trading symbol
            current_price: Current market price
            **kwargs: Additional validation data (volume profile, order flow, etc.)

        Returns:
            True if setup is valid and ready to trade

        Notes:
            - Used for live monitoring and conditional triggers
            - Should check capsule-specific entry conditions
        """
        pass

    def get_capital_config(self, key: str, default: Any = None) -> Any:
        """
        Get capsule-specific configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return self.config.get(key, default)

    def log_info(self, message: str):
        """Helper to log with capsule context."""
        logger.info(f"[{self.capsule_id}] {message}")

    def log_warning(self, message: str):
        """Helper to log warning with capsule context."""
        logger.warning(f"[{self.capsule_id}] {message}")

    def log_error(self, message: str):
        """Helper to log error with capsule context."""
        logger.error(f"[{self.capsule_id}] {message}")

    async def check_dependencies(self, **kwargs) -> bool:
        """
        Check if capsule dependencies are available.

        Capsules can override this to check for:
        - Required data feeds (OANDA, Kalshi, etc.)
        - Required tool functions (volume_profile, order_flow, etc.)
        - API keys/credentials

        Returns:
            True if all dependencies available

        Default implementation always returns True.
        """
        return True

    async def warm_up(self, **kwargs) -> Dict[str, Any]:
        """
        Optional warm-up routine for capsule.

        Capsules can override this to:
        - Cache historical data
        - Pre-calculate indicators
        - Initialize broker connections

        Returns:
            Dict with warm-up status/info

        Default implementation returns empty dict.
        """
        self.log_info("Warm-up complete")
        return {}

    async def shutdown(self):
        """
        Optional cleanup routine for capsule.

        Capsules can override this to:
        - Close API connections
        - Save cached data
        - Release resources

        Default implementation does nothing.
        """
        pass
