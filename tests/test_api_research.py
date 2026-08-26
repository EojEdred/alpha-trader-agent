"""Tests for the new dashboard/research/analyst/audit endpoints in dexter/api.py."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

# Set a web password before importing the app so auth is configured.
os.environ["DEXTER_WEB_PASSWORD"] = "testpass"

from dexter.api import app, create_session


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_cookies(client):
    resp = client.post("/api/login", json={"password": "testpass"})
    assert resp.status_code == 200
    return resp.cookies


def test_login_required(client):
    resp = client.get("/api/analysts")
    assert resp.status_code == 401


def test_list_analysts(client, auth_cookies):
    resp = client.get("/api/analysts", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    names = {a["name"] for a in data["analysts"]}
    assert "technical_analyst" in names
    assert "massive_analyst" in names


def test_run_analyst_unknown(client, auth_cookies):
    resp = client.post("/api/analysts/unknown_analyst/analyze", json={"symbol": "AAPL"}, cookies=auth_cookies)
    assert resp.status_code == 404


def test_run_analyst_massive(client, auth_cookies):
    with patch("agents.massive_analyst.MassiveProvider.get_ohlcv", new=AsyncMock(return_value={
        "candles": [
            {"close": 100, "volume": 1000},
            {"close": 101, "volume": 1000},
            {"close": 102, "volume": 1000},
            {"close": 103, "volume": 1000},
            {"close": 104, "volume": 1000},
            {"close": 105, "volume": 1000},
        ]
    })):
        with patch("agents.massive_analyst.MassiveProvider.get_snapshot", new=AsyncMock(return_value={"ticker": "AAPL", "day": {"c": 105.5}})):
            resp = client.post("/api/analysts/massive_analyst/analyze", json={"symbol": "AAPL"}, cookies=auth_cookies)

    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["agent_name"] == "massive_analyst"


def test_massive_market_data_disabled(client, auth_cookies):
    # No API key configured -> provider disabled
    resp = client.get("/api/market-data/AAPL/massive", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["ohlcv"] is None
    assert data["snapshot"] is None


def test_research_agendas_empty(client, auth_cookies):
    resp = client.get("/api/research/agendas", cookies=auth_cookies)
    assert resp.status_code == 200
    assert resp.json()["agendas"] == []


def test_audit_records(client, auth_cookies):
    resp = client.get("/api/audit?limit=5", cookies=auth_cookies)
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "integrity" in data


def test_phantomflow_webhook(client, auth_cookies):
    payload = {
        "ticker": "AAPL",
        "price": 150.0,
        "alert": "Phantom Shift Buy",
        "interval": "15m",
    }
    with patch("dexter.api.TradingEngine") as mock_engine_cls:
        mock_engine = mock_engine_cls.return_value
        mock_engine.submit_intent = AsyncMock()
        resp = client.post("/api/webhook/phantomflow", json=payload, cookies=auth_cookies)

    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    mock_engine.submit_intent.assert_awaited_once()
