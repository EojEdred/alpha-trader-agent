"""Tests for tools/risk_governor.py and enhanced circuit breakers."""

import pytest

from models import TradeIntent, TradeStatus
from models import ExecutionMode
from tools.risk_governor import RiskGovernor
from tools.circuit_breakers import check_drawdown_breaker, check_parse_failure_breaker


def make_intent(
    symbol="AAPL",
    direction="long",
    entry=100,
    stop=98,
    target=105,
    size=100,
    rr=2.5,
):
    from datetime import datetime, timedelta
    from models import generate_intent_id

    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="test",
        thesis_id="test",
        symbol=symbol,
        direction=direction,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        conviction=0.8,
        invalidation_price=stop,
        time_stop=datetime.utcnow() + timedelta(hours=4),
        risk_reward_ratio=rr,
        size=size,
        execution_mode=ExecutionMode.CONFIRM,
        venue="schwab",
        status=TradeStatus.PENDING,
    )


@pytest.mark.asyncio
async def test_valid_intent_approved():
    config = {"portfolio": {"max_risk_per_trade_pct": 5.0}}
    governor = RiskGovernor(config)
    intent = make_intent()
    decision = await governor.validate(intent, {"account_value": 60000})
    assert decision.approved is True


@pytest.mark.asyncio
async def test_rejects_missing_symbol():
    governor = RiskGovernor()
    intent = make_intent(symbol="")
    decision = await governor.validate(intent)
    assert decision.approved is False
    assert "symbol" in decision.rejection_reason.lower()


@pytest.mark.asyncio
async def test_rejects_bad_stop_for_long():
    governor = RiskGovernor()
    intent = make_intent(stop=101)
    decision = await governor.validate(intent)
    assert decision.approved is False
    assert "stop" in decision.rejection_reason.lower()


@pytest.mark.asyncio
async def test_rejects_risk_limit():
    config = {"portfolio": {"max_risk_per_trade_pct": 0.1}}
    governor = RiskGovernor(config)
    intent = make_intent(size=1000, entry=100, stop=99)
    decision = await governor.validate(intent, {"account_value": 10000})
    assert decision.approved is False
    assert "risk" in decision.rejection_reason.lower()


@pytest.mark.asyncio
async def test_rejects_drawdown():
    config = {
        "portfolio": {"max_risk_per_trade_pct": 5.0},
        "risk": {"max_drawdown_pct": 10.0},
    }
    governor = RiskGovernor(config)
    intent = make_intent()
    decision = await governor.validate(intent, {"account_value": 10000, "max_drawdown_pct": 15.0})
    assert decision.approved is False
    assert "drawdown" in decision.rejection_reason.lower()


@pytest.mark.asyncio
async def test_rejects_consecutive_losses():
    config = {"portfolio": {"consecutive_loss_limit": 2}}
    governor = RiskGovernor(config)
    intent = make_intent()
    decision = await governor.validate(intent, {"consecutive_losses": 3})
    assert decision.approved is False


@pytest.mark.asyncio
async def test_parse_failure_breaker():
    config = {"risk": {"parse_failure_limit": 2}}
    governor = RiskGovernor(config)
    governor.record_parse_failure()
    governor.record_parse_failure()
    intent = make_intent()
    decision = await governor.validate(intent)
    assert decision.approved is False
    assert "parse" in decision.rejection_reason.lower()


def test_check_drawdown_breaker():
    result = check_drawdown_breaker(80000, 100000, 15)
    assert result["halted"] is True
    assert result["drawdown_pct"] == pytest.approx(20.0, abs=0.01)

    result = check_drawdown_breaker(95000, 100000, 50)
    assert result["halted"] is False


def test_check_parse_failure_breaker():
    assert check_parse_failure_breaker(2, 3)["halted"] is False
    assert check_parse_failure_breaker(3, 3)["halted"] is True
