"""
XAUUSD Macro Levels Capsule

Macro level trading for XAUUSD (Gold).
OANDA executable mode - can directly place trades.
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from capsules import BaseCapsule
from models import ThesisObject, TradeIntent, ExecutionMode, generate_intent_id


class XAUUSDMacroLevelsCapsule(BaseCapsule):
    """
    XAUUSD (Gold) macro level trading.

    Logic:
    - Macro level identification (daily, weekly, monthly)
    - Regime alignment with thesis bias
    - Trend-following with macro confirmation
    - OANDA executable (AUTO mode)
    """

    @property
    def capsule_id(self) -> str:
        return "xauusd_macro_levels"

    @property
    def name(self) -> str:
        return "XAUUSD Macro Levels"

    @property
    def symbols(self) -> List[str]:
        return ["XAUUSD"]

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.AUTO

    async def generate_intents(
        self, thesis: ThesisObject, market_data: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        intents = []
        self.log_info("Generating XAUUSD macro level trade intents")

        try:
            xauusd_ohlcv = market_data.get("xauusd_ohlcv", [])
            if len(xauusd_ohlcv) < 50:
                self.log_warning("Insufficient XAUUSD OHLCV data")
                return intents

            xauusd_technicals = market_data.get("xauusd_technicals", {})

            current_price = xauusd_ohlcv[-1]["close"]

            macro_levels = self._calculate_macro_levels(xauusd_ohlcv)
            trend = xauusd_technicals.get("trend", "neutral")
            rsi = xauusd_technicals.get("indicators", {}).get("rsi_14", 50)

            direction = None
            entry_price = None
            stop_price = None
            target_price = None

            if thesis.regime_bias.value == "risk_on":
                if current_price <= macro_levels["daily"] * 1.002:
                    if trend == "bearish":
                        direction = "long"
                        entry_price = current_price
                        stop_price = macro_levels["daily"] * 0.99
                        target_price = macro_levels["weekly"]
                        conviction = thesis.conviction * 0.9
                    else:
                        self.log_info("Risk-on but trend not bearish")
                        return intents
                elif current_price >= macro_levels["daily"] * 0.998:
                    if trend == "bullish":
                        direction = "short"
                        entry_price = current_price
                        stop_price = macro_levels["daily"] * 1.01
                        target_price = macro_levels["weekly"]
                        conviction = thesis.conviction * 0.9
                    else:
                        self.log_info("Risk-on but trend not bullish")
                        return intents
            elif thesis.regime_bias.value == "risk_off":
                if rsi > 70:
                    direction = "short"
                    entry_price = current_price
                    stop_price = macro_levels["weekly"]
                    target_price = macro_levels["monthly"]
                    conviction = thesis.conviction * 0.85
                elif rsi < 30:
                    direction = "long"
                    entry_price = current_price
                    stop_price = macro_levels["weekly"]
                    target_price = macro_levels["monthly"]
                    conviction = thesis.conviction * 0.85
                else:
                    self.log_info("Risk-off but RSI neutral")
                    return intents
            else:
                if current_price <= macro_levels["daily"] and trend == "bullish":
                    direction = "long"
                    entry_price = current_price
                    stop_price = macro_levels["daily"] * 0.985
                    target_price = macro_levels["weekly"]
                    conviction = thesis.conviction * 0.8
                elif current_price >= macro_levels["daily"] and trend == "bearish":
                    direction = "short"
                    entry_price = current_price
                    stop_price = macro_levels["daily"] * 1.015
                    target_price = macro_levels["weekly"]
                    conviction = thesis.conviction * 0.8

            if direction:
                risk_per_share = abs(entry_price - stop_price)
                reward_per_share = abs(target_price - entry_price)
                risk_reward_ratio = (
                    reward_per_share / risk_per_share if risk_per_share > 0 else 0
                )

                if risk_reward_ratio >= 2.0:
                    intent = TradeIntent(
                        id=generate_intent_id(),
                        capsule_id=self.capsule_id,
                        thesis_id=thesis.id,
                        symbol="XAUUSD",
                        direction=direction,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        target_price=target_price,
                        conviction=conviction,
                        invalidation_price=stop_price * 1.5
                        if direction == "long"
                        else stop_price * 0.5,
                        time_stop=datetime.utcnow() + timedelta(days=7),
                        risk_reward_ratio=risk_reward_ratio,
                        execution_mode=self.execution_mode,
                        venue="oanda",
                        evidence_citations=thesis.evidence_ids,
                        tags=["macro_levels", thesis.regime_bias.value, trend],
                    )
                    intents.append(intent)
                    self.log_info(
                        f"Generated XAUUSD intent: {direction} @ {entry_price:.2f}"
                    )

        except Exception as e:
            self.log_error(f"Failed to generate XAUUSD intent: {e}")

        self.log_info(f"Generated {len(intents)} trade intents")
        return intents

    def _calculate_macro_levels(self, ohlcv: List[Dict]) -> Dict[str, float]:
        if not ohlcv or len(ohlcv) < 30:
            return {}

        closes = [bar["close"] for bar in ohlcv[-30:]]
        daily_levels = self._get_pivot_levels(closes[-25:])
        weekly_levels = self._get_pivot_levels(closes)
        monthly_levels = self._get_pivot_levels(closes)

        return {
            "daily": daily_levels["pivot"],
            "weekly": weekly_levels["pivot"],
            "monthly": monthly_levels["pivot"],
        }

    def _get_pivot_levels(self, closes: List[float]) -> Dict[str, float]:
        if not closes:
            return {"pivot": closes[-1] if closes else 0, "high": 0, "low": 0}

        high = max(closes)
        low = min(closes)
        pivot = (high + low + closes[-1]) / 3

        return {"pivot": pivot, "high": high, "low": low}

    async def validate_setup(self, symbol: str, current_price: float, **kwargs) -> bool:
        macro_levels = kwargs.get("macro_levels", {})
        if not macro_levels:
            return False

        daily_pivot = macro_levels.get("daily", current_price)
        if abs(current_price - daily_pivot) / daily_pivot > 0.02:
            return False

        return True
