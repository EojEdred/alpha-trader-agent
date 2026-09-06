"""
Strategy Registry

Manages all available strategies. Discovers, loads, and runs them.

Usage:
    from strategies.registry import StrategyRegistry

    registry = StrategyRegistry()
    registry.discover()  # Auto-load all strategies

    # Run a specific strategy
    signals = registry.run("vwap_trend", data)

    # Run all strategies
    all_signals = registry.run_all(data)
"""

import inspect
import importlib
import pkgutil
from typing import Dict, List, Any, Optional, Type
from pathlib import Path
from loguru import logger

from strategies.base import BaseStrategy, Signal


class StrategyRegistry:
    """Registry for discovering and running trading strategies."""

    def __init__(self):
        self._strategies: Dict[str, BaseStrategy] = {}
        self._classes: Dict[str, Type[BaseStrategy]] = {}

    def _register_module(self, module_name: str):
        """Import a strategy module and register its BaseStrategy subclasses."""
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.warning(f"Failed to load strategy module {module_name}: {e}")
            return

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, BaseStrategy) and obj is not BaseStrategy and hasattr(obj, "name"):
                try:
                    strategy = obj()
                    self._strategies[strategy.name] = strategy
                    self._classes[strategy.name] = obj
                    logger.debug(f"Registered strategy: {strategy.name}")
                except Exception as e:
                    logger.warning(f"Failed to instantiate strategy {name} from {module_name}: {e}")

    def discover(self):
        """Auto-discover all strategy classes in the strategies package."""
        import strategies

        package_path = Path(strategies.__file__).parent

        # Native strategies in strategies/
        for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
            if module_name in ("base", "registry", "fmz_parser", "fmz_runtime", "data_feed", "confluence"):
                continue
            self._register_module(f"strategies.{module_name}")

        # Auto-generated FMZ strategies in strategies/generated/batch_*
        generated_dir = package_path / "generated"
        if generated_dir.exists():
            for batch_dir in sorted(generated_dir.iterdir()):
                if not batch_dir.is_dir() or not batch_dir.name.startswith("batch_"):
                    continue
                for _, module_name, _ in pkgutil.iter_modules([str(batch_dir)]):
                    self._register_module(f"strategies.generated.{batch_dir.name}.{module_name}")

        logger.info(f"Strategy registry loaded: {len(self._strategies)} strategies")

    def register(self, name: str, strategy: BaseStrategy):
        """Manually register a strategy instance."""
        self._strategies[name] = strategy

    def get(self, name: str) -> Optional[BaseStrategy]:
        """Get a strategy by name."""
        return self._strategies.get(name)

    def list_strategies(self) -> List[Dict[str, str]]:
        """List all registered strategies with metadata."""
        return [s.info() for s in self._strategies.values()]

    def run(self, name: str, data: Dict[str, Any]) -> List[Signal]:
        """Run a single strategy and return signals."""
        strategy = self._strategies.get(name)
        if not strategy:
            logger.error(f"Strategy not found: {name}")
            return []

        try:
            signals = strategy.generate_signals(data)
            logger.info(f"Strategy '{name}' generated {len(signals)} signals")
            return signals
        except Exception as e:
            logger.exception(f"Strategy '{name}' failed: {e}")
            return []

    def run_all(self, data: Dict[str, Any]) -> Dict[str, List[Signal]]:
        """Run all strategies and return signals grouped by strategy name."""
        results = {}
        for name, strategy in self._strategies.items():
            try:
                signals = strategy.generate_signals(data)
                if signals:
                    results[name] = signals
                    logger.info(f"Strategy '{name}': {len(signals)} signals")
            except Exception as e:
                logger.exception(f"Strategy '{name}' failed: {e}")
        return results

    def to_trade_intents(self, signals: List[Signal], venue_map: Optional[Dict[str, str]] = None) -> List["TradeIntent"]:
        """Convert signals to TradeIntents with venue routing."""
        from models import TradeIntent, generate_intent_id

        venue_map = venue_map or {
            "NQ": "topstep",
            "ES": "topstep",
            "CL": "topstep",
            "GC": "topstep",
            "XAU_USD": "oanda",
            "EUR_USD": "oanda",
            "GBP_USD": "oanda",
        }

        intents = []
        for signal in signals:
            strategy = self._strategies.get(signal.strategy_name)
            if not strategy:
                continue

            venue = "schwab"  # Default
            for prefix, v in venue_map.items():
                if prefix in signal.symbol.upper():
                    venue = v
                    break

            intent = strategy.to_trade_intent(signal, venue=venue)
            intents.append(intent)

        return intents
