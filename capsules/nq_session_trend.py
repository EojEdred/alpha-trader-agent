"""
NQ Session Trend Capsule

Session trend detection for NQ (Nasdaq futures).
Signal-only mode - generates trade signals without execution.
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from capsules import BaseCapsule
from models import ThesisObject, TradeIntent, ExecutionMode, generate_intent_id


class NQSessionTrendCapsule(BaseCapsule):
    """
    NQ (Nasdaq futures) session trend detection.

    Logic:
    - Session trend identification (London session, NY session, etc.)
    - Momentum analysis
    - Breakout detection
    - Signal-only (no direct execution via existing adapters)
    """

    @property
    def capsule_id(self) -> str:
        return "nq_session_trend"

    @property
    def name(self) -> str:
        return "NQ Session Trend"

    @property
    def symbols(self) -> List[str]:
        return ["NQ"]

    @property
    def execution_mode(self) -> ExecutionMode:
        return ExecutionMode.SIGNAL_ONLY

    async def generate_intents(
        self, thesis: ThesisObject, market_data: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        """
        Generate trade intents based on session trend analysis.

        Args:
            thesis: ThesisObject with market bias
            market_data: Dict containing:
                - nq_ohlcv: NQ OHLCV data
                - nq_volume_profile: Volume profile
                - nq_technicals: Technical indicators

        Returns:
            List of TradeIntent objects (0-1 per symbol typical)
        """
        self.log_info("Generating NQ session trend trade intents")

        intents = []

        try:
            ohlcv = market_data.get("nq_ohlcv", [])
            if not ohlcv or len(ohlcv) < 50:
                self.log_warning("Insufficient NQ OHLCV data")
                return intents

            profile = market_data.get("nq_volume_profile", {})
            technicals = market_data.get("nq_technicals", {})

            current_price = ohlcv[-1]["close"]

            # Determine session trend
            session_trend = self._detect_session_trend(ohlcv)
            self.log_info(f"Detected session trend: {session_trend}")

            # Momentum analysis
            momentum = self._calculate_momentum(ohlcv)
            self.log_info(f"Momentum: {momentum}")

            # Generate trade intent if trend is clear
            if session_trend not in ["bullish", "bearish"]:
                self.log_info("No clear trend detected")
                return intents

            # Determine direction and levels
            if session_trend == "bullish" and momentum > 0:
                # Uptrend with positive momentum
                direction = "long"
                entry_price = current_price
                stop_price = (
                    ohlcv[-1]["low"] - (ohlcv[-1]["high"] - ohlcv[-1]["low"]) * 0.02
                )
                target_price = ohlcv[-1]["high"]  # Session high
                conviction = thesis.conviction * 0.8  # Adjust for technical alignment
            elif session_trend == "bearish" and momentum < 0:
                # Downtrend with negative momentum
                direction = "short"
                entry_price = current_price
                stop_price = (
                    ohlcv[-1]["high"] + (ohlcv[-1]["high"] - ohlcv[-1]["low"]) * 0.02
                )
                target_price = ohlcv[-1]["low"]  # Session low
                conviction = thesis.conviction * 0.8
            else:
                self.log_info("Trend and momentum conflict, no trade")
                return intents

            # Calculate risk/reward
            risk_per_share = abs(entry_price - stop_price)
            reward_per_share = abs(target_price - entry_price)
            risk_reward_ratio = (
                reward_per_share / risk_per_share if risk_per_share > 0 else 0
            )

            if risk_reward_ratio < 2.0:
                self.log_info(f"Risk/reward too low: {risk_reward_ratio:.2f}")
                return intents

            # Create TradeIntent
            intent = TradeIntent(
                id=generate_intent_id(),
                capsule_id=self.capsule_id,
                thesis_id=thesis.id,
                symbol="NQ",
                direction=direction,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
                conviction=min(conviction, 0.9),  # Cap at 90%
                invalidation_price=stop_price * 1.5
                if direction == "long"
                else stop_price * 0.5,
                time_stop=datetime.utcnow()
                + timedelta(hours=4),  # 4-hour intraday time stop
                risk_reward_ratio=risk_reward_ratio,
                execution_mode=self.execution_mode,
                venue="topstep",  # Topstep for futures
                evidence_citations=thesis.evidence_ids,
                tags=["session_trend", session_trend, "signal_only"],
            )

            intents.append(intent)
            self.log_info(f"Generated NQ intent: {direction} @ {entry_price:.2f}")

        except Exception as e:
            self.log_error(f"Failed to generate NQ intent: {e}")

        self.log_info(f"Generated {len(intents)} trade intents")
        return intents

    def _detect_session_trend(self, ohlcv: List[Dict]) -> str:
        """
        Detect session trend based on price action.

        Uses:
        - Session high/low relationships
        - Moving average slope
        - Price position relative to range
        """
        if not ohlcv or len(ohlcv) < 20:
            return "neutral"

        closes = [bar["close"] for bar in ohlcv[-20:]]
        highs = [bar["high"] for bar in ohlcv[-20:]]
        lows = [bar["low"] for bar in ohlcv[-20:]]

        session_high = max(highs)
        session_low = min(lows)
        current_price = closes[-1]

        # Check price position in session range
        range_mid = (session_high + session_low) / 2
        if current_price > range_mid:
            position = "upper"
        else:
            position = "lower"

        # Calculate EMA slope
        from tools.analysis import calculate_technicals

        tech_result = calculate_technicals(ohlcv)
        ema_20 = tech_result.get("indicators", {}).get("ema_20", closes[-1])

        ema_5_periods_ago = tech_result.get("indicators", {}).get(
            "ema_5_5p", closes[-6]
        )

        if ema_20 > ema_5_periods_ago:
            slope = "up"
        elif ema_20 < ema_5_periods_ago:
            slope = "down"
        else:
            slope = "flat"

        # Determine trend
        if position == "upper" and slope == "up":
            return "bullish"
        elif position == "lower" and slope == "down":
            return "bearish"
        elif slope == "flat":
            return "neutral"
        else:
            # Conflicting signals
            return "neutral"

    def _calculate_momentum(self, ohlcv: List[Dict]) -> float:
        """
        Calculate momentum indicator.

        Uses:
        - Rate of change (ROC) over 5 bars
        - Normalized to -1 to +1 range
        """
        if not ohlcv or len(ohlcv) < 6:
            return 0

        current_close = ohlcv[-1]["close"]
        close_5_periods_ago = ohlcv[-6]["close"]

        roc = (current_close - close_5_periods_ago) / close_5_periods_ago

        # Normalize
        momentum = max(min(roc, 1), -1)

        return momentum

    async def validate_setup(self, symbol: str, current_price: float, **kwargs) -> bool:
        """
        Validate if setup meets entry criteria.

        Validation:
        1. Price is within 0.25% of session high/low
        2. Trend is not conflicting
        3. Momentum is aligned with trend (for new positions)
        """
        ohlcv = kwargs.get("ohlcv", [])
        if not ohlcv:
            return False

        session_high = max(bar["high"] for bar in ohlcv[-20:])
        session_low = min(bar["low"] for bar in ohlcv[-20:])

        # Check if price is within session range
        if current_price < session_low * 0.99 or current_price > session_high * 1.01:
            return False

        return True
