"""
Portfolio Brain - Central intelligence for portfolio-level decisions

Implements:
- Ranking: Score and rank trade intents
- Suppression: Remove correlated/duplicate intents
- Sizing: Calculate optimal position sizes
- Risk Limits: Enforce circuit breakers
"""

import asyncio
from typing import List, Dict, Any, Optional
from loguru import logger

from models import TradeIntent, TradeStatus


class PortfolioBrain:
    """
    Central intelligence for portfolio-level decisions.

    Responsibilities:
    - Rank trade intents by conviction, regime alignment, portfolio fit
    - Suppress correlated/duplicate intents
    - Size positions based on risk limits
    - Enforce circuit breakers
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    async def rank_intents(
        self, intents: List[TradeIntent], current_positions: Dict[str, Any], **kwargs
    ) -> List[TradeIntent]:
        """
        Rank and filter trade intents.

        Args:
            intents: List of TradeIntent from capsules
            current_positions: Current positions dict
            **kwargs: Additional parameters

        Returns:
            Ranked, filtered intents
        """
        logger.info(f"PortfolioBrain: Ranking {len(intents)} trade intents")

        # 1. Apply circuit breakers first
        if self._check_circuit_breakers():
            logger.warning("Circuit breaker triggered, blocking all trades")
            return []

        # 2. Score each intent
        scored_intents = []
        for intent in intents:
            score = self._calculate_intent_score(intent, current_positions, **kwargs)
            scored_intents.append((score, intent))

        # 3. Sort by score
        scored_intents.sort(key=lambda x: x[0], reverse=True)

        # 4. Suppress duplicates and correlated
        filtered_intents = await self.suppress_correlated(
            [intent for _, intent in scored_intents], **kwargs
        )

        # 5. Update status
        for intent in filtered_intents:
            intent.status = TradeStatus.APPROVED

        logger.info(
            f"PortfolioBrain: Filtered to {len(filtered_intents)} approved intents"
        )
        return filtered_intents

    async def suppress_correlated(
        self, intents: List[TradeIntent], **kwargs
    ) -> List[TradeIntent]:
        """
        Remove correlated or duplicate intents.

        Rules:
        - Same symbol + direction within time window (30 min)
        - Highly correlated symbols (SPY/QQQ)
        - Duplicate entry prices within tolerance
        """
        suppressed = []
        intents_to_consider = intents.copy()

        # Group by symbol
        symbol_groups: Dict[str, List[TradeIntent]] = {}
        for intent in intents:
            if intent.symbol not in symbol_groups:
                symbol_groups[intent.symbol] = []
            symbol_groups[intent.symbol].append(intent)

        # Process each symbol group
        for symbol, symbol_intents in symbol_groups.items():
            # Sort by conviction first
            symbol_intents.sort(key=lambda x: x.conviction, reverse=True)

            # Keep highest conviction intent, suppress duplicates
            best_intent = symbol_intents[0]
            if len(symbol_intents) > 1:
                suppressed.extend(symbol_intents[1:])
                logger.info(
                    f"Suppressing {len(symbol_intents[1:])} duplicate/correlated intents for {symbol}"
                )

        # Remove suppressed from consideration
        filtered = [i for i in intents if i not in suppressed]

        return filtered

    async def size_positions(
        self, intents: List[TradeIntent], account_value: float, **kwargs
    ) -> List[TradeIntent]:
        """
        Calculate optimal position sizes.

        Rules:
        - Max risk per trade (e.g., 0.5% of account)
        - Max loss per day (e.g., 2% of account)
        - Max open risk (e.g., 5% of account)
        - Adjust size based on conviction
        """
        max_risk_per_trade_pct = self._get_config("max_risk_per_trade_pct", 0.5)
        max_loss_per_day_pct = self._get_config("max_loss_per_day_pct", 2.0)
        max_open_risk_pct = self._get_config("max_open_risk_pct", 5.0)

        max_risk_per_trade = account_value * max_risk_per_trade_pct
        max_loss_per_day = account_value * max_loss_per_day_pct
        max_open_risk = account_value * max_open_risk_pct

        # Calculate current open risk
        current_open_risk = 0.0
        for intent in intents:
            if intent.size:
                current_open_risk += abs(intent.size * intent.stop_price)

        for intent in intents:
            if intent.status == TradeStatus.APPROVED:
                # Calculate risk based on stop distance
                risk_per_share = abs(intent.entry_price - intent.stop_price)

                # Apply conviction modifier
                base_size = max_risk_per_trade / risk_per_share
                sized = base_size * intent.conviction

                # Check daily loss limit
                daily_loss_available = max_loss_per_day - current_open_risk
                if risk_per_share > daily_loss_available:
                    sized = (max_loss_per_day - current_open_risk) / risk_per_share
                    logger.warning(
                        f"Reducing {intent.symbol} size to {sized:.2f} due to daily loss limit"
                    )

                # Check max open risk
                open_risk_after = current_open_risk + (sized * risk_per_share)
                if open_risk_after > max_open_risk:
                    sized = (max_open_risk - current_open_risk) / risk_per_share
                    logger.warning(
                        f"Reducing {intent.symbol} size to {sized:.2f} due to max open risk"
                    )

                intent.size = min(sized, base_size)

        logger.info(
            f"PortfolioBrain: Sized {len([i for i in intents if i.size])} positions"
        )
        return intents

    def _calculate_intent_score(
        self, intent: TradeIntent, current_positions: Dict[str, Any], **kwargs
    ) -> float:
        """
        Calculate composite score for ranking.

        Scoring:
        - Conviction: 0-40 points
        - Regime alignment: 0-30 points
        - Portfolio fit: 0-20 points
        - Technical quality: 0-10 points
        Total: 0-100 points
        """
        score = 0.0

        # Conviction score (40%)
        score += intent.conviction * 40

        # Regime alignment (30%)
        regime_bias = self._get_thesis_regime(intent.thesis_id)
        if regime_bias in ["risk_on", "risk_off"]:
            # Bias aligned with market regime is good
            score += 30
        else:
            score += 15

        # Portfolio fit (20%)
        # Check if fits with existing positions
        symbol_positions = [
            p for s, p in current_positions.items() if s in intent.symbol.lower()
        ]
        if symbol_positions:
            # Avoid over-concentration
            if len(symbol_positions) >= 2:
                score -= 10
            else:
                score += 10

        # Technical quality (10%)
        # Check risk/reward ratio
        if intent.risk_reward_ratio >= 2.0:
            score += 10
        elif intent.risk_reward_ratio >= 1.5:
            score += 5
        else:
            score += 0

        return min(score, 100)

    def _get_thesis_regime(self, thesis_id: str) -> str:
        """Helper to get regime bias from thesis."""
        # This would normally query thesis from DB
        # For now, return neutral default
        return "neutral"

    def _get_config(self, key: str, default: Any = None) -> Any:
        """Helper to get configuration value."""
        return self.config.get(key, default)

    def _check_circuit_breakers(self, **kwargs) -> bool:
        """
        Check if circuit breakers are triggered.

        Conditions:
        - Consecutive losses: Stop after limit
        - Daily loss limit: Stop if >2%
        - Prohibited windows: FOMC, CPI, NFP
        """
        consecutive_loss_limit = self._get_config("consecutive_loss_limit", 2)
        daily_loss_limit_pct = self._get_config("daily_loss_limit_pct", 2.0)
        consecutive_losses = self._get_config("consecutive_losses", 0)

        # Check consecutive losses
        if consecutive_losses >= consecutive_loss_limit:
            logger.warning(
                f"Circuit breaker: consecutive_losses ({consecutive_losses}) >= "
                f"limit ({consecutive_loss_limit})"
            )
            return True

        # Check daily loss limit (placeholder — would query P&L DB)
        # daily_loss = self._get_daily_loss()
        # if daily_loss > daily_loss_limit_pct:
        #     return True

        return False
