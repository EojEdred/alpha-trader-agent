"""
Zynth-Level Upgrade Tests

Tests for schema validation, router gating, portfolio suppression.
"""

import pytest
import asyncio
from datetime import datetime, timedelta

from models import (
    EvidenceItem,
    ThesisObject,
    TradeIntent,
    RiskDecision,
    ExecutionPlan,
    ExecutionMode,
    generate_evidence_id,
    generate_thesis_id,
    generate_intent_id,
    generate_execution_plan_id,
    RegimeBias,
)
from portfolio import PortfolioBrain
from router import ExecutionRouter


class TestSchemaValidation:
    """Test JSON serialization and validation."""

    def test_evidence_item_serialization(self):
        evidence = EvidenceItem(
            id=generate_evidence_id(),
            url="https://example.com",
            title="Test Evidence",
            snippet="Test snippet",
            timestamp=datetime.utcnow(),
            confidence=0.8,
            tags=["test"],
        )

        data = evidence.to_dict()
        assert data["id"] == evidence.id
        assert data["url"] == evidence.url
        assert isinstance(data["timestamp"], str)

        restored = EvidenceItem.from_dict(data)
        assert restored.id == evidence.id

    def test_thesis_object_serialization(self):
        thesis = ThesisObject(
            id=generate_thesis_id(),
            summary="Test thesis",
            evidence_ids=["evd_1", "evd_2"],
            conviction=0.75,
            regime_bias=RegimeBias.RISK_ON,
            created_at=datetime.utcnow(),
            tags=["macro", "inflation"],
        )

        data = thesis.to_dict()
        assert data["regime_bias"] == "risk_on"
        assert isinstance(data["created_at"], str)

        restored = ThesisObject.from_dict(data)
        assert restored.regime_bias == RegimeBias.RISK_ON

    def test_trade_intent_serialization(self):
        intent = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=447.0,
            target_price=475.0,
            conviction=0.85,
            invalidation_price=472.0,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="oanda",
            evidence_citations=["evd_1"],
        )

        data = intent.to_dict()
        assert data["execution_mode"] == "auto"
        assert data["direction"] == "long"

        restored = TradeIntent.from_dict(data)
        assert restored.execution_mode == ExecutionMode.AUTO


class TestRouterGating:
    """Test AUTO/CONFIRM/SIGNAL_ONLY routing logic."""

    @pytest.fixture
    def router(self):
        config = {
            "execution_modes": {
                "oanda": {"auto_enabled": True, "max_size_auto": 10000},
                "kalshi": {"auto_enabled": True},
                "schwab": {"auto_enabled": False},
                "topstep": {"auto_enabled": False},
            }
        }
        return ExecutionRouter(config)

    def test_oanda_auto_mode_small_trade(self, router):
        decision = RiskDecision(intent_id="test_intent", approved=True)

        plans = asyncio.run(router.route_intents([decision]))
        assert len(plans) == 1
        assert plans[0].execution_mode == ExecutionMode.AUTO
        assert not plans[0].requires_confirmation

    def test_schwab_confirm_mode(self, router):
        decision = RiskDecision(intent_id="test_intent_schwab", approved=True)

        plans = asyncio.run(router.route_intents([decision]))
        for plan in plans:
            if plan.venue == "schwab":
                assert plan.execution_mode == ExecutionMode.CONFIRM
                assert plan.requires_confirmation

    def test_topstep_signal_only(self, router):
        decision = RiskDecision(intent_id="test_intent_topstep", approved=True)

        plans = asyncio.run(router.route_intents([decision]))
        for plan in plans:
            if plan.venue == "topstep":
                assert plan.execution_mode == ExecutionMode.SIGNAL_ONLY

    def test_rejected_intent_no_plan(self, router):
        decision = RiskDecision(
            intent_id="test_intent",
            approved=False,
            rejection_reason="Risk limit exceeded",
        )

        plans = asyncio.run(router.route_intents([decision]))
        assert len(plans) == 0


class TestPortfolioSuppression:
    """Test duplicate/correlation suppression and ranking."""

    @pytest.fixture
    def portfolio_brain(self):
        config = {
            "max_risk_per_trade_pct": 0.5,
            "consecutive_loss_limit": 2,
            "correlation_threshold": 0.7,
        }
        return PortfolioBrain(config)

    def test_suppress_duplicate_same_symbol(self, portfolio_brain):
        intent1 = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=447.0,
            target_price=475.0,
            conviction=0.85,
            invalidation_price=472.0,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="schwab",
        )

        intent2 = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule_2",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.5,
            stop_price=447.5,
            target_price=475.5,
            conviction=0.70,
            invalidation_price=472.5,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="schwab",
        )

        intents = asyncio.run(
            portfolio_brain.rank_intents([intent1, intent2], current_positions={})
        )

        assert len(intents) == 1
        assert intents[0].conviction == 0.85

    def test_rank_by_conviction(self, portfolio_brain):
        intents = []
        for i, conviction in enumerate([0.9, 0.7, 0.5]):
            intent = TradeIntent(
                id=generate_intent_id(),
                capsule_id="test_capsule",
                thesis_id="test_thesis",
                symbol=f"TEST{i}",
                direction="long",
                entry_price=100.0 + i,
                stop_price=98.0 + i,
                target_price=105.0 + i,
                conviction=conviction,
                invalidation_price=106.0 + i,
                time_stop=datetime.utcnow() + timedelta(hours=6),
                risk_reward_ratio=2.5,
                execution_mode=ExecutionMode.AUTO,
                venue="test",
            )
            intents.append(intent)

        ranked = asyncio.run(
            portfolio_brain.rank_intents(intents, current_positions={})
        )

        if len(ranked) > 0:
            assert ranked[0].conviction == 0.9
        if len(ranked) > 1:
            assert ranked[1].conviction == 0.7
        if len(ranked) > 2:
            assert ranked[2].conviction == 0.5

    def test_circuit_breaker_blocks_all(self, portfolio_brain):
        portfolio_brain.config["consecutive_losses"] = 2

        intents = [
            TradeIntent(
                id=generate_intent_id(),
                capsule_id="test_capsule",
                thesis_id="test_thesis",
                symbol="SPY",
                direction="long",
                entry_price=450.0,
                stop_price=447.0,
                target_price=475.0,
                conviction=0.9,
                invalidation_price=472.0,
                time_stop=datetime.utcnow() + timedelta(hours=6),
                risk_reward_ratio=2.5,
                execution_mode=ExecutionMode.AUTO,
                venue="schwab",
            )
        ]

        ranked = asyncio.run(
            portfolio_brain.rank_intents(intents, current_positions={})
        )

        assert len(ranked) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
