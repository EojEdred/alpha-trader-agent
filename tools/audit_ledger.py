"""
Hash-Chained Audit Ledger for Alpha Trader

Records every event in the trading pipeline with a SHA-256 hash chained to
the previous record. This creates a tamper-evident audit trail similar to
Vibe-Trading's hash-chained ledger.

Each record contains:
- seq: monotonic sequence number
- timestamp: ISO UTC
- type: event type (research, decision, execution, etc.)
- payload: JSON-serializable event data
- previous_hash: hash of previous record ("0" for genesis)
- hash: SHA-256 of the canonicalized record

Usage:
    from tools.audit_ledger import AuditLedger

    ledger = AuditLedger()
    record = await ledger.append("trade_intent", {"symbol": "SPY", "side": "long"})
    assert ledger.verify()
"""

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class AuditRecord:
    """Single tamper-evident audit record."""

    seq: int
    timestamp: str
    type: str
    payload: Dict[str, Any]
    previous_hash: str
    hash: str


class AuditLedger:
    """
    SQLite-backed hash-chained audit ledger.
    """

    def __init__(self, db_path: Optional[str] = None):
        default_path = os.getenv("ALPHA_TRADER_AUDIT_DB_PATH") or str(
            Path.home() / ".alphatrader" / "audit_ledger.db"
        )
        self.db_path = db_path or default_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create ledger table if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_ledger (
                    seq INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    hash TEXT NOT NULL
                )
            """)

    def _canonical(self, record: Dict[str, Any]) -> str:
        """Canonical JSON for hashing (excludes the hash field itself)."""
        clean = {k: v for k, v in record.items() if k != "hash"}
        return json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str)

    def _hash(self, record: Dict[str, Any]) -> str:
        """Compute SHA-256 of canonical record."""
        return hashlib.sha256(self._canonical(record).encode("utf-8")).hexdigest()

    def _get_last_hash(self) -> str:
        """Get the hash of the most recent record, or genesis hash."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT hash FROM audit_ledger ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else "0" * 64

    async def append(
        self,
        record_type: str,
        payload: Dict[str, Any],
    ) -> AuditRecord:
        """
        Append a new record to the ledger.

        Args:
            record_type: Event type (e.g. "research", "execution").
            payload: JSON-serializable event data.

        Returns:
            AuditRecord with assigned sequence and hash.
        """
        timestamp = datetime.utcnow().isoformat()
        previous_hash = self._get_last_hash()

        with sqlite3.connect(self.db_path) as conn:
            # Use MAX(seq) + 1 to support gaps/resets safely
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM audit_ledger").fetchone()
            seq = (row[0] or 0) + 1

        raw = {
            "seq": seq,
            "timestamp": timestamp,
            "type": record_type,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        record_hash = self._hash(raw)
        raw["hash"] = record_hash

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_ledger (seq, timestamp, type, payload, previous_hash, hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (seq, timestamp, record_type, json.dumps(payload, default=str), previous_hash, record_hash),
            )

        logger.debug(f"AuditLedger: appended record {seq} ({record_type})")
        return AuditRecord(
            seq=seq,
            timestamp=timestamp,
            type=record_type,
            payload=payload,
            previous_hash=previous_hash,
            hash=record_hash,
        )

    def get_records(
        self,
        record_type: Optional[str] = None,
        start_seq: Optional[int] = None,
        end_seq: Optional[int] = None,
        limit: int = 1000,
    ) -> List[AuditRecord]:
        """Query records with optional filters."""
        query = "SELECT seq, timestamp, type, payload, previous_hash, hash FROM audit_ledger WHERE 1=1"
        params: List[Any] = []

        if record_type:
            query += " AND type = ?"
            params.append(record_type)
        if start_seq is not None:
            query += " AND seq >= ?"
            params.append(start_seq)
        if end_seq is not None:
            query += " AND seq <= ?"
            params.append(end_seq)

        query += " ORDER BY seq ASC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        records = []
        for row in rows:
            payload = json.loads(row[3])
            records.append(
                AuditRecord(
                    seq=row[0],
                    timestamp=row[1],
                    type=row[2],
                    payload=payload,
                    previous_hash=row[4],
                    hash=row[5],
                )
            )
        return records

    def verify(self) -> Dict[str, Any]:
        """
        Verify the integrity of the entire ledger.

        Returns:
            {"valid": bool, "records_checked": int, "first_bad_seq": Optional[int]}
        """
        records = self.get_records(limit=1000000)
        if not records:
            return {"valid": True, "records_checked": 0, "first_bad_seq": None}

        previous_hash = "0" * 64
        for record in records:
            raw = {
                "seq": record.seq,
                "timestamp": record.timestamp,
                "type": record.type,
                "payload": record.payload,
                "previous_hash": record.previous_hash,
            }
            expected_hash = self._hash(raw)
            if record.previous_hash != previous_hash or record.hash != expected_hash:
                logger.error(
                    f"AuditLedger: integrity check failed at seq {record.seq}"
                )
                return {
                    "valid": False,
                    "records_checked": record.seq,
                    "first_bad_seq": record.seq,
                }
            previous_hash = record.hash

        return {
            "valid": True,
            "records_checked": len(records),
            "first_bad_seq": None,
        }

    def replay(
        self,
        record_type: Optional[str] = None,
        start_seq: int = 1,
    ) -> List[AuditRecord]:
        """
        Replay records from a starting sequence.

        Returns all matching records in order, useful for reconstructing a
        trading session or debugging a decision.
        """
        return self.get_records(record_type=record_type, start_seq=start_seq, limit=1000000)

    def reset(self):
        """Clear the ledger. Use with caution."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM audit_ledger")
        logger.warning("AuditLedger: all records deleted")
