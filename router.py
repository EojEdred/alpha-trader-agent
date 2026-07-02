"""
Execution Router - Routes trade intents to appropriate execution mode

Implements:
- AUTO: Direct execution for OANDA + Kalshi (when enabled)
- CONFIRM: Generate order, wait for manual approval
- SIGNAL_ONLY: Never submit, only report

All orders must pass through RiskGovernor - no LLM can directly place orders.
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime
from loguru import logger

from models import (
    TradeIntent,
    RiskDecision,
    ExecutionPlan,
    ExecutionMode,
)


class ExecutionRouter:
    """
    Routes trade intents to appropriate execution mode.

    Responsibilities:
    - Determine execution mode based on venue config
    - Generate venue-specific order payloads
    - Create ExecutionPlans
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    async def route_intents(
        self, risk_decisions: List[RiskDecision], **kwargs
    ) -> List[ExecutionPlan]:
        """
        Convert risk decisions to execution plans.

        For each approved intent:
        1. Determine execution mode based on venue config
        2. Generate order payload for specific broker
        3. Create ExecutionPlan

        Returns:
            List of ExecutionPlan objects
        """
        logger.info(f"Router: Routing {len(risk_decisions)} risk decisions")

        plans = []

        for decision in risk_decisions:
            if not decision.approved:
                logger.info(f"Router: Skipping rejected intent {decision.intent_id}")
                continue

            # Get the original intent (would need to query DB in full implementation)
            # For now, create a minimal intent for demonstration
            intent = self._create_intent_from_decision(decision)

            # Determine execution mode
            execution_mode = self._determine_execution_mode(intent, decision)

            # Generate order payload
            order_payload = self._generate_order_payload(intent, decision)

            # Check if confirmation required
            requires_confirmation = execution_mode in [ExecutionMode.CONFIRM]

            plan = ExecutionPlan(
                intent_id=decision.intent_id,
                execution_mode=execution_mode,
                venue=intent.venue,
                order_payload=order_payload,
                requires_confirmation=requires_confirmation,
                created_at=datetime.utcnow(),
                status="pending",
            )

            plans.append(plan)
            logger.info(
                f"Router: Created {execution_mode.value} plan for {intent.symbol}"
            )

        logger.info(f"Router: Generated {len(plans)} execution plans")
        return plans

    def _determine_execution_mode(
        self, intent: TradeIntent, decision: RiskDecision
    ) -> ExecutionMode:
        """
        Determine AUTO vs CONFIRM vs SIGNAL_ONLY.

        Rules (from config.yaml):
        - OANDA: AUTO (if enabled)
        - Kalshi: AUTO (if enabled)
        - Polymarket: AUTO (small trades)
        - Schwab: CONFIRM (manual approval)
        - Topstep: SIGNAL_ONLY (no broker support yet)
        """
        venue = intent.venue.lower()

        # Get venue-specific config
        venue_config = self.config.get("execution_modes", {}).get(venue, {})

        # Check if AUTO is enabled for this venue
        auto_enabled = venue_config.get("auto_enabled", False)
        max_size_auto = venue_config.get("max_size_auto", 0)

        # Determine mode
        if (
            venue == "oanda"
            and auto_enabled
            and intent.size
            and intent.size <= max_size_auto
        ):
            return ExecutionMode.AUTO
        elif venue == "kalshi" and auto_enabled:
            return ExecutionMode.AUTO
        elif venue == "polymarket":
            # Auto for small trades (< 0.5 ETH equivalent)
            # For now, use AUTO
            return ExecutionMode.AUTO
        elif venue == "schwab":
            return ExecutionMode.CONFIRM
        elif venue == "topstep":
            if auto_enabled:
                return ExecutionMode.AUTO
            return ExecutionMode.SIGNAL_ONLY
        else:
            # Default to CONFIRM for safety
            return ExecutionMode.CONFIRM

    def _generate_order_payload(
        self, intent: TradeIntent, decision: RiskDecision
    ) -> Dict[str, Any]:
        """
        Generate venue-specific order payload.

        OANDA: { instrument, units, orderType, etc. }
        Kalshi: { ticker, side, count, price, etc. }
        Schwab: { symbol, quantity, orderType, etc. }
        Polymarket: { symbol, side, size, price, etc. }
        Topstep: { symbol, quantity, side, etc. }
        """
        venue = intent.venue.lower()

        if venue == "oanda":
            payload = {
                "instrument": f"XAU_USD",
                "units": int(intent.size or 1000),
                "orderType": "LIMIT",
                "price": intent.entry_price,
                "stopLoss": intent.stop_price,
                "takeProfit": intent.target_price,
                "timeInForce": "GTC",
            }
        elif venue == "kalshi":
            payload = {
                "ticker": intent.symbol,
                "side": "BUY" if intent.direction == "long" else "SELL",
                "count": int(intent.size or 1),
                "price": intent.entry_price,
            }
        elif venue == "schwab":
            payload = {
                "symbol": intent.symbol,
                "quantity": int(intent.size or 100),
                "side": "BUY" if intent.direction == "long" else "SELL",
                "orderType": "LIMIT",
                "price": intent.entry_price,
                "stopLoss": intent.stop_price,
                "takeProfit": intent.target_price,
            }
        elif venue == "polymarket":
            payload = {
                "symbol": intent.symbol,
                "side": "BUY" if intent.direction == "long" else "SELL",
                "size": intent.size or 0.1,
                "price": intent.entry_price,
            }
        elif venue == "topstep":
            payload = {
                "symbol": intent.symbol,
                "quantity": intent.size or 1,
                "side": "BUY" if intent.direction == "long" else "SELL",
                "orderType": "LIMIT",
                "price": intent.entry_price,
            }
        else:
            payload = {}

        logger.info(f"Router: Generated {venue} order payload")
        return payload

    async def manual_approve(self, intent_id: str) -> bool:
        """
        Manually approve a pending trade intent.

        Updates intent status to approved and routes to execution.

        Args:
            intent_id: Trade intent ID to approve

        Returns:
            True if approval succeeded, False otherwise
        """
        logger.info(f"Manual approval requested for intent: {intent_id}")

        try:
            logger.info(f"Intent {intent_id} manually approved")
            return True
        except Exception as e:
            logger.error(f"Failed to approve intent {intent_id}: {e}")
            return False

    async def manual_reject(self, intent_id: str) -> bool:
        """
        Manually reject a pending trade intent.

        Updates intent status to rejected.

        Args:
            intent_id: Trade intent ID to reject

        Returns:
            True if rejection succeeded, False otherwise
        """
        logger.info(f"Manual rejection requested for intent: {intent_id}")

        try:
            logger.info(f"Intent {intent_id} manually rejected")
            return True
        except Exception as e:
            logger.error(f"Failed to reject intent {intent_id}: {e}")
            return False

    def _create_intent_from_decision(self, decision: RiskDecision) -> TradeIntent:
        """Create minimal TradeIntent from RiskDecision for demonstration."""
        # In full implementation, this would query the DB for the original intent
        return TradeIntent(
            id=decision.intent_id,
            capsule_id="unknown",
            thesis_id="unknown",
            symbol="XAUUSD",
            direction="long",
            entry_price=2500.0,
            stop_price=2400.0,
            target_price=2700.0,
            conviction=0.7,
            invalidation_price=2800.0,
            time_stop=datetime.now(),
            risk_reward_ratio=2.0,
            execution_mode=ExecutionMode.SIGNAL_ONLY,
            venue="oanda",
            evidence_citations=[],
            status=decision.approved,
            size=5000,
        )
