"""Tests for tools/ccxt_gateway.py."""

import pytest

from tools.ccxt_gateway import CCXTGateway, CCXTGatewayError


class FakeCCXTClient:
    def __init__(self):
        self.markets = {"BTC/USDT": {"limits": {"amount": {"min": 0.001}}}}
        self.sandbox = False
        self.calls = []

    def set_sandbox_mode(self, enabled):
        self.sandbox = enabled

    async def load_markets(self):
        self.calls.append("load_markets")

    async def close(self):
        self.calls.append("close")

    def market(self, symbol):
        if symbol not in self.markets:
            raise Exception("Market not found")
        return self.markets[symbol]

    async def fetch_balance(self):
        return {"USDT": {"free": 1000}}

    async def fetch_ticker(self, symbol):
        return {"symbol": symbol, "last": 50000}

    async def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        self.calls.append(("create_order", symbol, order_type, side, amount, price, params))
        return {"id": "123", "symbol": symbol, "side": side, "amount": amount}

    async def cancel_order(self, order_id, symbol):
        return {"id": order_id, "status": "canceled"}

    async def fetch_order(self, order_id, symbol):
        return {"id": order_id, "symbol": symbol, "status": "closed"}


class FakeCCXTModule:
    exchanges = ["binance"]

    class binance:
        def __init__(self, config):
            self.config = config
            self.client = FakeCCXTClient()
            # Mirror attributes to self for gateway compatibility
            for attr in dir(self.client):
                if not attr.startswith("__"):
                    setattr(self, attr, getattr(self.client, attr))


@pytest.fixture
def fake_ccxt(monkeypatch):
    monkeypatch.setattr("tools.ccxt_gateway.ccxt_async", FakeCCXTModule())
    monkeypatch.setattr("tools.ccxt_gateway._CCXT_AVAILABLE", True)


@pytest.mark.asyncio
async def test_create_market_buy(fake_ccxt):
    gateway = CCXTGateway("binance", config={})
    await gateway.load_markets()
    order = await gateway.create_market_buy("BTC/USDT", 0.01)
    assert order["side"] == "buy"
    assert order["amount"] == 0.01


@pytest.mark.asyncio
async def test_invalid_side_raises(fake_ccxt):
    gateway = CCXTGateway("binance", config={})
    await gateway.load_markets()
    with pytest.raises(CCXTGatewayError):
        await gateway.create_order("BTC/USDT", "hold", 0.01)


@pytest.mark.asyncio
async def test_below_min_amount_raises(fake_ccxt):
    gateway = CCXTGateway("binance", config={})
    await gateway.load_markets()
    with pytest.raises(CCXTGatewayError, match="below minimum"):
        await gateway.create_market_buy("BTC/USDT", 0.0001)


@pytest.mark.asyncio
async def test_get_balance(fake_ccxt):
    gateway = CCXTGateway("binance", config={})
    await gateway.load_markets()
    balance = await gateway.get_balance()
    assert balance["USDT"]["free"] == 1000
