"""
Risk Governor for Alpha Trader

Validates TradeIntents before they become ExecutionPlans. Enforces:
- Symbol/price/size sanity checks
- Stop-loss and risk/reward rules
- Portfolio-level limits (daily loss, open risk, consecutive losses)
- Drawdown kill switch
- Per-venue and parse-failure circuit breakers

This is the gate between the Decision layer and the Control/Execution layers.
No trade executes without passing the RiskGovernor.

Usage:
    from tools.risk_governor import RiskGovernor

    governor = RiskGovernor(config)
    decision = await governor.validate(intent, portfolio_state)
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

from models import RiskDecision, TradeIntent, TradeStatus
from tools.circuit_breakers import check_circuit_breakers


class RiskGovernor:
    """
    Validates trade intents against configured risk limits and circuit breakers.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.portfolio_config = self.config.get("portfolio", {})
        self.risk_config = self.config.get("risk", {})

        self.max_risk_per_trade_pct = self.portfolio_config.get("max_risk_per_trade_pct", 0.5)
        self.max_loss_per_day_pct = self.portfolio_config.get("max_loss_per_day_pct", 2.0)
        self.max_open_risk_pct = self.portfolio_config.get("max_open_risk_pct", 5.0)
        self.consecutive_loss_limit = self.portfolio_config.get("consecutive_loss_limit", 2)
        self.min_risk_reward = self.config.get("risk_limits", {}).get("min_risk_reward", 2.0)
        self.max_drawdown_pct = self.risk_config.get("max_drawdown_pct", 50.0)

        self._parse_failures = 0
        self._parse_failure_limit = self.risk_config.get("parse_failure_limit", 3)

    async def validate(
        self,
        intent: TradeIntent,
        portfolio_state: Optional[Dict[str, Any]] = None,
    ) -> RiskDecision:
        """
        Validate a single TradeIntent.

        Args:
            intent: TradeIntent to validate.
            portfolio_state: Current portfolio snapshot.

        Returns:
            RiskDecision with approved=True/False and rejection reason.
        """
        portfolio_state = portfolio_state or {}
        warnings: List[str] = []

        # 1. Sanity checks
        if not intent.symbol or not intent.symbol.strip():
            return self._reject(intent, "Missing symbol")
        if intent.entry_price <= 0:
            return self._reject(intent, "Invalid entry price")
        if intent.size is None or intent.size <= 0:
            return self._reject(intent, "Invalid position size")

        # 2. Stop loss / invalidation checks
        if intent.direction == "long":
            if intent.stop_price >= intent.entry_price:
                return self._reject(intent, "Long stop loss must be below entry")
            if intent.target_price <= intent.entry_price:
                return self._reject(intent, "Long target must be above entry")
        else:
            if intent.stop_price <= intent.entry_price:
                return self._reject(intent, "Short stop loss must be above entry")
            if intent.target_price >= intent.entry_price:
                return self._reject(intent, "Short target must be below entry")

        # 3. Risk/reward check
        if intent.risk_reward_ratio < self.min_risk_reward:
            return self._reject(
                intent,
                f"Risk/reward {intent.risk_reward_ratio:.2f} below minimum {self.min_risk_reward}",
            )

        # 4. Portfolio limits
        account_value = portfolio_state.get("account_value", 100000.0)
        day_pnl = portfolio_state.get("day_pnl", 0.0)
        open_risk = portfolio_state.get("open_risk", 0.0)
        consecutive_losses = portfolio_state.get("consecutive_losses", 0)
        max_drawdown = portfolio_state.get("max_drawdown_pct", 0.0)

        # Per-trade risk in account percent
        trade_risk_dollars = abs(intent.size * (intent.entry_price - intent.stop_price))
        trade_risk_pct = (trade_risk_dollars / account_value) * 100 if account_value else 0

        if trade_risk_pct > self.max_risk_per_trade_pct:
            return self._reject(
                intent,
                f"Trade risk {trade_risk_pct:.2f}% exceeds max {self.max_risk_per_trade_pct}%",
            )

        # Daily loss limit
        if day_pnl < 0 and abs(day_pnl) >= (self.max_loss_per_day_pct / 100) * account_value:
            return self._reject(
                intent,
                f"Daily loss limit reached: ${day_pnl:.2f}",
            )

        # Open risk limit
        total_open_risk_pct = (open_risk + trade_risk_dollars) / account_value * 100
        if total_open_risk_pct > self.max_open_risk_pct:
            warnings.append(
                f"Open risk {total_open_risk_pct:.2f}% approaches limit {self.max_open_risk_pct}%"
            )

        # Consecutive losses
        if consecutive_losses >= self.consecutive_loss_limit:
            return self._reject(
                intent,
                f"Consecutive loss limit reached: {consecutive_losses}",
            )

        # Drawdown kill switch
        if max_drawdown >= self.max_drawdown_pct:
            return self._reject(
                intent,
                f"Max drawdown {max_drawdown:.2f}% >= kill switch {self.max_drawdown_pct}%",
            )

        # 5. Circuit breakers (global)
        cb_result = check_circuit_breakers(
            daily_pnl=day_pnl,
            consecutive_losses=consecutive_losses,
            account_equity=account_value,
        )
        if cb_result.get("halted"):
            return self._reject(intent, f"Circuit breaker: {cb_result.get('reason')}")

        # 6. Parse-failure / agent-error breaker
        if self._parse_failures >= self._parse_failure_limit:
            return self._reject(
                intent,
                f"Agent parse/risk failure limit: {self._parse_failures}",
            )

        # 7. Venue-specific checks
        venue = intent.venue.lower()
        venue_config = self.config.get("execution_modes", {}).get("venues", {}).get(venue, {})
        if not venue_config.get("auto_enabled", False) and venue != "schwab":
            warnings.append(f"Venue {venue} not enabled for auto execution")

        logger.info(
            f"RiskGovernor: approved {intent.symbol} {intent.direction} "
            f"(risk {trade_risk_pct:.2f}%)"
        )
        return RiskDecision(
            intent_id=intent.id,
            approved=True,
            warnings=warnings,
            checked_at=datetime.utcnow(),
        )

    def record_parse_failure(self):
        """Record an agent parse or risk assessment failure."""
        self._parse_failures += 1
        logger.warning(f"RiskGovernor: parse failure {self._parse_failures}/{self._parse_failure_limit}")

    def reset_parse_failures(self):
        """Reset parse failure counter (e.g. after successful cycle)."""
        self._parse_failures = 0

    def _reject(self, intent: TradeIntent, reason: str) -> RiskDecision:
        logger.warning(f"RiskGovernor: rejected {intent.symbol} — {reason}")
        return RiskDecision(
            intent_id=intent.id,
            approved=False,
            rejection_reason=reason,
            checked_at=datetime.utcnow(),
        )

    async def validate_batch(
        self,
        intents: List[TradeIntent],
        portfolio_state: Optional[Dict[str, Any]] = None,
    ) -> List[RiskDecision]:
        """Validate a batch of intents and return decisions."""
        decisions = []
        for intent in intents:
            decision = await self.validate(intent, portfolio_state)
            decisions.append(decision)
            if not decision.approved:
                # Optional: stop validating further intents after a rejection
                # decisions.extend([
                #     self._reject(i, "Batch halted after earlier rejection")
                #     for i in intents[len(decisions):]
                # ])
                # break
                pass
        return decisions
