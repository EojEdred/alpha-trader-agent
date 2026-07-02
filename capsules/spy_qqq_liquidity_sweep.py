"""
SPY/QQQ Liquidity Sweep Capsule

Wraps existing liquidity sweep logic from scoring.py.
Generates TradeIntents for SPY and QQQ based on:
- Volume profile analysis
- Order flow confirmation
- Liquidity sweep detection
- Session POC/FVA levels
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger

from capsules import BaseCapsule
from models import ThesisObject, TradeIntent, ExecutionMode, generate_intent_id


class SPYQQQLiquiditySweepCapsule(BaseCapsule):
    """
    Liquidity Sweep strategy for SPY and QQQ options.

    Logic wrapped from existing scoring.py:
    - Volume profile calculation
    - Order flow signals
    - A+ scoring system
    """

    @property
    def capsule_id(self) -> str:
        return "spy_qqq_liquidity_sweep"

    @property
    def name(self) -> str:
        return "SPY/QQQ Liquidity Sweep"

    @property
    def symbols(self) -> List[str]:
        return ["SPY", "QQQ"]

    @property
    def execution_mode(self) -> ExecutionMode:
        # Signal-only by default - futures not directly supported via existing adapters
        return ExecutionMode.SIGNAL_ONLY

    async def generate_intents(
        self, thesis: ThesisObject, market_data: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        """
        Generate trade intents based on liquidity sweep analysis.

        Args:
            thesis: ThesisObject with market bias
            market_data: Dict containing:
                - ohlcv_data: Price data
                - volume_profile: Volume profile data
                - order_flow: Order flow signals
                - technicals: Technical indicators

        Returns:
            List of TradeIntent objects (0-2, one per symbol)
        """
        self.log_info("Generating liquidity sweep trade intents")

        intents = []

        for symbol in self.symbols:
            try:
                # Get market data for this symbol
                ohlcv = market_data.get(f"{symbol}_ohlcv", [])
                profile = market_data.get(f"{symbol}_profile", {})
                order_flow = market_data.get(f"{symbol}_order_flow", {})
                technicals = market_data.get(f"{symbol}_technicals", {})

                if not ohlcv or not profile:
                    self.log_warning(f"Insufficient market data for {symbol}")
                    continue

                # Get current price
                current_price = ohlcv[-1]["close"] if ohlcv else 0

                # Call existing scoring logic
                from tools.scoring import score_setup

                score_result = await score_setup(symbol)

                # Check if setup meets minimum criteria
                if not score_result.trade_allowed:
                    self.log_info(f"Setup for {symbol} does not meet criteria")
                    continue

                # Calculate entry/exit based on volume profile
                poc = profile.get("poc", current_price)
                fva_high = profile.get("fva_high", current_price * 1.01)
                fva_low = profile.get("fva_low", current_price * 0.99)

                # Determine direction based on thesis and technicals
                trend = technicals.get("trend", "neutral")
                rsi = technicals.get("indicators", {}).get("rsi_14", 50)

                # Logic: if thesis is risk_on and rsi < 30 → bounce long
                #           if thesis is risk_off and rsi > 70 → fade short
                #           if at POC with order flow confirmation → trade the bounce
                if thesis.regime_bias.value == "risk_on":
                    if rsi < 30:
                        direction = "long"
                        entry_price = fva_low
                        stop_price = fva_low - (fva_high - fva_low) * 0.1
                        target_price = poc
                    elif rsi > 70:
                        direction = "short"
                        entry_price = fva_high
                        stop_price = fva_high + (fva_high - fva_low) * 0.1
                        target_price = poc
                    else:
                        self.log_info(f"No clear bias setup for {symbol}")
                        continue
                elif thesis.regime_bias.value == "risk_off":
                    # Fade rallies at FVA edges
                    if current_price >= fva_high * 0.995:
                        direction = "short"
                        entry_price = current_price
                        stop_price = fva_high + (fva_high - fva_low) * 0.05
                        target_price = fva_low
                    elif current_price <= fva_low * 1.005:
                        direction = "long"
                        entry_price = current_price
                        stop_price = fva_low - (fva_high - fva_low) * 0.05
                        target_price = fva_high
                    else:
                        self.log_info(f"Price not at FVA edge for {symbol}")
                        continue
                else:
                    # Neutral regime - trade POC bounces
                    if abs(current_price - poc) / poc < 0.005:  # Within 0.5% of POC
                        # Check order flow for confirmation
                        if order_flow.get("flow_score", 0) >= 15:
                            if order_flow.get("cvd", {}).get("state") == "confirming":
                                direction = "long" if trend == "bullish" else "short"
                                entry_price = poc
                                stop_price = (
                                    fva_low if direction == "long" else fva_high
                                )
                                target_price = (
                                    fva_high if direction == "long" else fva_low
                                )
                            else:
                                self.log_info(f"Order flow not confirmed for {symbol}")
                                continue
                        else:
                            self.log_info(f"Price not near POC for {symbol}")
                            continue
                    else:
                        self.log_info(f"Neutral regime, no clear setup for {symbol}")
                        continue

                # Calculate risk/reward
                risk_per_share = abs(entry_price - stop_price)
                reward_per_share = abs(target_price - entry_price)
                risk_reward_ratio = (
                    reward_per_share / risk_per_share if risk_per_share > 0 else 0
                )

                # Only generate if risk/reward >= 2:1
                if risk_reward_ratio < 2.0:
                    self.log_info(
                        f"Risk/reward ratio too low for {symbol}: {risk_reward_ratio:.2f}"
                    )
                    continue

                # Create TradeIntent
                intent = TradeIntent(
                    id=generate_intent_id(),
                    capsule_id=self.capsule_id,
                    thesis_id=thesis.id,
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    target_price=target_price,
                    conviction=thesis.conviction
                    * score_result.size_modifier,  # Combine thesis + setup conviction
                    invalidation_price=fva_high if direction == "long" else fva_low,
                    time_stop=datetime.utcnow()
                    + timedelta(hours=6),  # 6-hour time stop
                    risk_reward_ratio=risk_reward_ratio,
                    execution_mode=self.execution_mode,
                    venue="schwab",  # SPY/QQQ via Schwab for now
                    evidence_citations=thesis.evidence_ids,
                    tags=["liquidity_sweep", thesis.regime_bias.value, trend],
                )

                intents.append(intent)
                self.log_info(
                    f"Generated intent for {symbol}: {direction} @ {entry_price:.2f}"
                )

            except Exception as e:
                self.log_error(f"Failed to generate intent for {symbol}: {e}")
                continue

        self.log_info(f"Generated {len(intents)} trade intents")
        return intents

    async def validate_setup(self, symbol: str, current_price: float, **kwargs) -> bool:
        """
        Validate if setup meets entry criteria.

        Validation:
        1. Current price within 0.5% of POC or FVA edge
        2. Order flow score >= 15
        3. Risk/reward >= 2:1
        """
        profile = kwargs.get("profile", {})
        order_flow = kwargs.get("order_flow", {})

        if not profile:
            return False

        poc = profile.get("poc", current_price)
        fva_high = profile.get("fva_high", current_price)
        fva_low = profile.get("fva_low", current_price)

        # Check if price is at valid location
        near_poc = abs(current_price - poc) / poc < 0.005
        near_fva_high = abs(current_price - fva_high) / fva_high < 0.005
        near_fva_low = abs(current_price - fva_low) / fva_low < 0.005

        if not (near_poc or near_fva_high or near_fva_low):
            return False

        # Check order flow confirmation
        flow_score = order_flow.get("flow_score", 0)
        if flow_score < 15:
            return False

        # Check CVD state
        cvd_state = order_flow.get("cvd", {}).get("state", "")
        if cvd_state not in ["confirming", "diverging"]:
            return False

        return True
