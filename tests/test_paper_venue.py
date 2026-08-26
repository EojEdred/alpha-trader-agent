"""Tests for tools/paper_venue.py."""

import pytest

from tools.paper_venue import PaperVenue


@pytest.mark.asyncio
async def test_buy_updates_balances_and_position():
    venue = PaperVenue(initial_balance={"USD": 10000})
    fill = await venue.place_order("AAPL", "buy", 10, price=150)

    assert fill.side == "buy"
    assert fill.filled_price > 150  # slippage
    assert fill.fee > 0
    assert venue.get_balance("USD")["USD"] < 10000
    assert venue.get_balance("AAPL")["AAPL"] == 10

    pos = venue.get_position("AAPL")
    assert pos.side == "long"
    assert pos.size == 10


@pytest.mark.asyncio
async def test_sell_reduces_position():
    venue = PaperVenue(initial_balance={"USD": 10000, "AAPL": 10})
    await venue.place_order("AAPL", "buy", 10, price=150)
    await venue.place_order("AAPL", "sell", 5, price=155)

    pos = venue.get_position("AAPL")
    assert pos.size == 5


@pytest.mark.asyncio
async def test_crypto_fee_model():
    venue = PaperVenue(initial_balance={"USDT": 10000})
    fill = await venue.place_order("BTC/USDT", "buy", 0.1, price=50000)
    assert fill.fee == pytest.approx(0.1 * fill.filled_price * 0.001, rel=1e-3)


@pytest.mark.asyncio
async def test_liquidation():
    venue = PaperVenue(initial_balance={"USDT": 10000})
    await venue.place_order("BTC/USDT", "buy", 1.0, price=50000, leverage=20)
    pos = await venue.check_liquidation("BTC/USDT", mark_price=40000)
    assert pos is not None
    assert "BTC/USDT" not in venue.positions


@pytest.mark.asyncio
async def test_funding():
    venue = PaperVenue(initial_balance={"USDT": 10000})
    await venue.place_order("BTC/USDT", "buy", 1.0, price=50000, leverage=10)
    await venue.apply_funding("BTC/USDT", funding_rate=0.0001, mark_price=50000)
    pnl = venue.get_pnl()
    assert pnl["realized_funding"] > 0


def test_detect_asset_class():
    venue = PaperVenue()
    assert venue._detect_asset_class("BTC/USDT") == "crypto"
    assert venue._detect_asset_class("ES") == "futures"
    assert venue._detect_asset_class("EURUSD") == "forex"
    assert venue._detect_asset_class("AAPL") == "default"
