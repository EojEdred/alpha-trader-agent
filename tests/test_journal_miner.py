"""Tests for tools/journal_miner.py."""

import csv
from pathlib import Path

import pytest

from tools.journal_miner import JournalMiner


@pytest.fixture
def sample_journal(tmp_path):
    path = tmp_path / "journal.csv"
    rows = [
        {
            "symbol": "AAPL",
            "side": "long",
            "entry_price": "150",
            "exit_price": "155",
            "size": "100",
            "pnl": "500",
            "notes": "Breakout momentum",
        },
        {
            "symbol": "AAPL",
            "side": "long",
            "entry_price": "155",
            "exit_price": "152",
            "size": "100",
            "pnl": "-300",
            "notes": "Pullback",
        },
        {
            "symbol": "TSLA",
            "side": "short",
            "entry_price": "250",
            "exit_price": "240",
            "size": "50",
            "pnl": "500",
            "notes": "Momentum short",
        },
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.asyncio
async def test_mine_journal(sample_journal):
    miner = JournalMiner(config={})
    result = await miner.mine(str(sample_journal), use_vibe=False)

    assert result["trades"] == 3
    assert result["win_rate"] == 2 / 3
    assert result["total_pnl"] == 700
    assert "AAPL" in result["symbols"]
    assert any("AAPL" in rule for rule in result["rules"])


@pytest.mark.asyncio
async def test_mine_journal_uses_vibe(sample_journal, monkeypatch):
    called = {" shadow": None}

    async def fake_shadow(path):
        called["shadow"] = path
        return {"delta_pnl": 0.1}

    miner = JournalMiner(config={})
    miner.vibe.shadow_backtest = fake_shadow
    result = await miner.mine(str(sample_journal), use_vibe=True)
    assert result["shadow_backtest"]["delta_pnl"] == 0.1


def test_normalize_trade_handles_aliases():
    miner = JournalMiner()
    trade = miner._normalize_trade(
        {
            "symbol": "spy",
            "side": "LONG",
            "entry_price": "400",
            "exit_price": "405",
            "size": "10",
            "pnl": "50",
        }
    )
    assert trade["symbol"] == "SPY"
    assert trade["side"] == "long"
    assert trade["entry_price"] == 400.0
