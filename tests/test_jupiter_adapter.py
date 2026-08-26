"""Tests for tools/jupiter_adapter.py."""

import pytest

from tools.jupiter_adapter import JupiterAdapter, JupiterError


class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            from httpx import HTTPStatusError
            raise HTTPStatusError("error", request=None, response=self)


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    async def get(self, endpoint, params=None):
        self.calls.append(("GET", endpoint, params))
        key = endpoint.split("?")[0]
        data = self.responses.get(key)
        if isinstance(data, Exception):
            raise data
        return FakeResponse(data)

    async def post(self, endpoint, json=None):
        self.calls.append(("POST", endpoint, json))
        data = self.responses.get(endpoint)
        if isinstance(data, Exception):
            raise data
        return FakeResponse(data)

    async def aclose(self):
        pass


@pytest.fixture
def adapter():
    config = {"jupiter": {"timeout_seconds": 10}}
    return JupiterAdapter(config)


@pytest.mark.asyncio
async def test_get_quote(adapter):
    adapter._client = FakeHTTPClient({
        "/swap/v1/quote": {
            "inputMint": "SOL",
            "outputMint": "USDC",
            "outAmount": "100000000",
        }
    })
    quote = await adapter.get_quote("SOL", "USDC", 1.0)
    assert quote["inputMint"] == "SOL"
    assert quote["outAmount"] == "100000000"


@pytest.mark.asyncio
async def test_get_token_list(adapter):
    adapter._client = FakeHTTPClient({
        "/tokens/v1/tagged/verified": [{"symbol": "SOL", "address": "..."}]
    })
    tokens = await adapter.get_token_list()
    assert isinstance(tokens, list)


@pytest.mark.asyncio
async def test_get_swap_transaction_requires_key(adapter):
    adapter._client = FakeHTTPClient({})
    adapter.private_key = None
    with pytest.raises(JupiterError, match="private key not configured"):
        await adapter.get_swap_transaction({})


@pytest.mark.asyncio
async def test_swap_without_solana_sdk(adapter, monkeypatch):
    monkeypatch.setattr("tools.jupiter_adapter._SOLANA_AVAILABLE", False)
    result = await adapter.swap("SOL", "USDC", 1.0)
    assert result is None
