"""Tests for tools/phantomflow_parser.py."""

import pytest

from models import ExecutionMode
from tools.phantomflow_parser import PhantomFlowParser


@pytest.mark.asyncio
async def test_parse_phantom_shift_buy():
    parser = PhantomFlowParser()
    intent = await parser.parse_webhook(
        {"ticker": "AAPL", "price": 150.0, "alert": "Phantom Shift Buy", "interval": "15m"}
    )
    assert intent is not None
    assert intent.symbol == "AAPL"
    assert intent.direction == "long"
    assert intent.conviction == 0.55
    assert intent.execution_mode == ExecutionMode.CONFIRM
    assert intent.stop_price < intent.entry_price
    assert intent.target_price > intent.entry_price


@pytest.mark.asyncio
async def test_parse_combo_confluence_sell():
    parser = PhantomFlowParser()
    intent = await parser.parse_webhook(
        {"ticker": "TSLA", "price": 250.0, "alert": "Combo Confluence Sell"}
    )
    assert intent.direction == "short"
    assert intent.conviction == 0.60


@pytest.mark.asyncio
async def test_parse_unrecognized_alert():
    parser = PhantomFlowParser()
    intent = await parser.parse_webhook(
        {"ticker": "SPY", "price": 450.0, "alert": "Random alert"}
    )
    assert intent is None


@pytest.mark.asyncio
async def test_parse_missing_fields():
    parser = PhantomFlowParser()
    intent = await parser.parse_webhook({"ticker": "SPY"})
    assert intent is None


@pytest.mark.asyncio
async def test_signal_only_when_not_require_confirmation():
    parser = PhantomFlowParser(config={"phantomflow": {"require_confirmation": False}})
    intent = await parser.parse_webhook(
        {"ticker": "BTCUSDT", "price": 50000.0, "alert": "Phantom Shift Buy"}
    )
    assert intent.execution_mode == ExecutionMode.SIGNAL_ONLY
