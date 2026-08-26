"""Tests for tools/audit_ledger.py."""

import pytest

from tools.audit_ledger import AuditLedger


@pytest.fixture
async def ledger(tmp_path):
    path = tmp_path / "audit.db"
    led = AuditLedger(db_path=str(path))
    yield led


@pytest.mark.asyncio
async def test_append_and_verify(tmp_path):
    ledger = AuditLedger(db_path=str(tmp_path / "audit.db"))
    r1 = await ledger.append("research", {"symbol": "SPY"})
    r2 = await ledger.append("execution", {"symbol": "SPY", "side": "buy"})

    assert r1.seq == 1
    assert r2.seq == 2
    assert r2.previous_hash == r1.hash

    result = ledger.verify()
    assert result["valid"] is True
    assert result["records_checked"] == 2


@pytest.mark.asyncio
async def test_query_by_type(tmp_path):
    ledger = AuditLedger(db_path=str(tmp_path / "audit.db"))
    await ledger.append("research", {"symbol": "SPY"})
    await ledger.append("execution", {"symbol": "QQQ"})
    await ledger.append("research", {"symbol": "AAPL"})

    research = ledger.get_records(record_type="research")
    assert len(research) == 2
    assert all(r.type == "research" for r in research)


@pytest.mark.asyncio
async def test_tamper_detection(tmp_path):
    ledger = AuditLedger(db_path=str(tmp_path / "audit.db"))
    await ledger.append("research", {"symbol": "SPY"})

    import sqlite3
    with sqlite3.connect(ledger.db_path) as conn:
        conn.execute("UPDATE audit_ledger SET payload = '{\"tampered\": true}'")

    result = ledger.verify()
    assert result["valid"] is False
    assert result["first_bad_seq"] == 1
