"""
Kalshi Macro Sensor Capsule

Regime detection and risk-on/off bias for prediction markets.
Kalshi executable mode - can directly place trades.
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from capsules import BaseCapsule
from models import ThesisObject, TradeIntent, ExecutionMode, generate_intent_id


class KalshiMacroSensorCapsule(BaseCapsule):
    @property
    def capsule_id(self) -> str:
        return "kalshi_macro_sensor"

    @property
    def name(self) -> str:
        return "Kalshi Macro Sensor"

    @property
    def symbols(self) -> List[str]:
        return []

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.AUTO

    async def generate_intents(
        self, thesis: ThesisObject, market_data: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        intents = []
        self.log_info("Generating Kalshi macro sensor trade intents")

        try:
            kalshi_data = market_data.get("kalshi_markets", [])

            regime_flags = self._detect_regime_flags(kalshi_data)
            self.log_info(f"Detected regime flags: {regime_flags}")

            if thesis.regime_bias.value == "risk_on" and regime_flags.get(
                "inflation_rising", False
            ):
                for market in kalshi_data:
                    if (
                        market.get("market_id", "").startswith("INFLATION")
                        and market.get("yes_price", 0.5) < 0.3
                    ):
                        intent = TradeIntent(
                            id=generate_intent_id(),
                            capsule_id=self.capsule_id,
                            thesis_id=thesis.id,
                            symbol=market.get("ticker", ""),
                            direction="buy",
                            entry_price=market.get("yes_price", 0),
                            stop_price=market.get("no_price", 0),
                            target_price=market.get("yes_price", 1.0),
                            conviction=thesis.conviction * 0.8,
                            invalidation_price=0.4,
                            time_stop=datetime.utcnow() + timedelta(days=90),
                            risk_reward_ratio=2.5,
                            execution_mode=self.execution_mode,
                            venue="kalshi",
                            evidence_citations=thesis.evidence_ids,
                            tags=[
                                "kalshi",
                                "inflation",
                                "risk_on",
                                thesis.regime_bias.value,
                            ],
                        )
                        intents.append(intent)
                        self.log_info(
                            f"Generated Kalshi intent: buy {market.get('ticker')}"
                        )

            elif thesis.regime_bias.value == "risk_off" and regime_flags.get(
                "inflation_falling", False
            ):
                for market in kalshi_data:
                    if (
                        market.get("market_id", "").startswith("INFLATION")
                        and market.get("no_price", 0.5) > 0.7
                    ):
                        intent = TradeIntent(
                            id=generate_intent_id(),
                            capsule_id=self.capsule_id,
                            thesis_id=thesis.id,
                            symbol=market.get("ticker", ""),
                            direction="sell",
                            entry_price=market.get("no_price", 0),
                            stop_price=market.get("yes_price", 0),
                            target_price=market.get("no_price", 0.1),
                            conviction=thesis.conviction * 0.8,
                            invalidation_price=0.9,
                            time_stop=datetime.utcnow() + timedelta(days=90),
                            risk_reward_ratio=2.5,
                            execution_mode=self.execution_mode,
                            venue="kalshi",
                            evidence_citations=thesis.evidence_ids,
                            tags=[
                                "kalshi",
                                "inflation",
                                "risk_off",
                                thesis.regime_bias.value,
                            ],
                        )
                        intents.append(intent)
                        self.log_info(
                            f"Generated Kalshi intent: sell {market.get('ticker')}"
                        )

        except Exception as e:
            self.log_error(f"Failed to generate Kalshi intent: {e}")

        self.log_info(f"Generated {len(intents)} trade intents")
        return intents

    def _detect_regime_flags(self, kalshi_data: List[Dict]) -> Dict[str, bool]:
        flags = {
            "inflation_rising": False,
            "inflation_falling": False,
            "volatility_spike": False,
        }

        yes_prices = [
            m.get("yes_price", 0)
            for m in kalshi_data
            if "INFLATION" in m.get("market_id", "")
        ]
        if yes_prices:
            avg_yes = sum(yes_prices) / len(yes_prices)
            flags["inflation_rising"] = avg_yes > 0.45
            flags["inflation_falling"] = avg_yes < 0.25

        return flags

    async def validate_setup(self, symbol: str, current_price: float, **kwargs) -> bool:
        market_id = kwargs.get("market_id", "")
        if not market_id:
            return False

        if "INFLATION" in market_id:
            price = kwargs.get("price", current_price)
            return 0.05 <= price <= 0.95

        return True
