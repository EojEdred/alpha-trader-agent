"""
Persistent Memory / Audit Log

Tracks every decision in the trading pipeline for review and learning.
Uses SQLite for persistence, with JSON columns for structured data.

Inspired by TradingAgents' TradingMemoryLog.

Usage:
    from tools.memory_log import MemoryLog

    log = MemoryLog()
    log.record_analyst_report(report)
    log.record_research_plan(plan)
    log.record_trade_proposal(proposal)
    log.record_risk_assessment(assessment)
    log.record_final_decision(decision)

    # Query history
    reports = log.get_reports_for_symbol("SPY", days=7)
    decisions = log.get_decisions(verdict="approve", days=30)
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import asdict
from loguru import logger


class MemoryLog:
    """Persistent audit trail for all trading decisions."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(Path.home() / ".alphatrader" / "memory.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analyst_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    key_points TEXT,  -- JSON list
                    risks TEXT,       -- JSON list
                    evidence TEXT,    -- JSON dict
                    reasoning TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    recommendation TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    analyst_agreement TEXT,
                    rationale TEXT,
                    strategic_actions TEXT,
                    divergent_views TEXT,  -- JSON list
                    reports_considered TEXT,  -- JSON list
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    position_size INTEGER,
                    risk_amount REAL,
                    risk_reward_ratio REAL,
                    venue TEXT,
                    rationale TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS risk_assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    confidence REAL,
                    concerns TEXT,     -- JSON list
                    mitigations TEXT,  -- JSON list
                    correlated_exposure TEXT,  -- JSON list
                    reasoning TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS final_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    approved_size INTEGER,
                    approved_entry REAL,
                    approved_stop REAL,
                    approved_target REAL,
                    execution_venue TEXT,
                    reasoning TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    decision_id INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    exit_reason TEXT,
                    raw_json TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_symbol ON analyst_reports(symbol);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_decisions_symbol ON final_decisions(symbol);
            """)
            conn.commit()

    def _now(self) -> str:
        return datetime.utcnow().isoformat()

    def record_analyst_report(self, report):
        """Record an analyst report."""
        from models.decision_schemas import AnalystReport
        if isinstance(report, AnalystReport):
            data = report.model_dump()
        else:
            data = report

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO analyst_reports
                (timestamp, agent_name, symbol, direction, confidence, key_points, risks,
                 evidence, reasoning, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._now(),
                data.get("agent_name", ""),
                data.get("symbol", ""),
                data.get("direction", ""),
                data.get("confidence", 0),
                json.dumps(data.get("key_points", [])),
                json.dumps(data.get("risks", [])),
                json.dumps(data.get("evidence", {})),
                data.get("reasoning", ""),
                json.dumps(data),
            ))
            conn.commit()

    def record_research_plan(self, plan):
        """Record a research plan."""
        from models.decision_schemas import ResearchPlan
        if isinstance(plan, ResearchPlan):
            data = plan.model_dump()
        else:
            data = plan

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO research_plans
                (timestamp, symbol, recommendation, confidence, analyst_agreement,
                 rationale, strategic_actions, divergent_views, reports_considered, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._now(),
                data.get("symbol", ""),
                data.get("recommendation", ""),
                data.get("confidence", 0),
                data.get("analyst_agreement", ""),
                data.get("rationale", ""),
                data.get("strategic_actions", ""),
                json.dumps(data.get("divergent_views", [])),
                json.dumps(data.get("reports_considered", [])),
                json.dumps(data),
            ))
            conn.commit()

    def record_trade_proposal(self, proposal):
        """Record a trade proposal."""
        from models.decision_schemas import TradeProposal
        if isinstance(proposal, TradeProposal):
            data = proposal.model_dump()
        else:
            data = proposal

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trade_proposals
                (timestamp, symbol, action, entry_price, stop_loss, take_profit,
                 position_size, risk_amount, risk_reward_ratio, venue, rationale, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._now(),
                data.get("symbol", ""),
                data.get("action", ""),
                data.get("entry_price", 0),
                data.get("stop_loss", 0),
                data.get("take_profit", 0),
                data.get("position_size", 0),
                data.get("risk_amount", 0),
                data.get("risk_reward_ratio", 0),
                data.get("venue", ""),
                data.get("rationale", ""),
                json.dumps(data),
            ))
            conn.commit()

    def record_risk_assessment(self, assessment):
        """Record a risk assessment."""
        from models.decision_schemas import RiskAssessment
        if isinstance(assessment, RiskAssessment):
            data = assessment.model_dump()
        else:
            data = assessment

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO risk_assessments
                (timestamp, symbol, verdict, confidence, concerns, mitigations,
                 correlated_exposure, reasoning, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._now(),
                data.get("symbol", ""),
                data.get("verdict", ""),
                data.get("confidence", 0),
                json.dumps(data.get("concerns", [])),
                json.dumps(data.get("mitigations", [])),
                json.dumps(data.get("correlated_exposure", [])),
                data.get("reasoning", ""),
                json.dumps(data),
            ))
            conn.commit()

    def record_final_decision(self, decision):
        """Record a final decision."""
        from models.decision_schemas import FinalDecision
        if isinstance(decision, FinalDecision):
            data = decision.model_dump()
        else:
            data = decision

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO final_decisions
                (timestamp, symbol, verdict, approved_size, approved_entry,
                 approved_stop, approved_target, execution_venue, reasoning, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self._now(),
                data.get("symbol", ""),
                data.get("verdict", ""),
                data.get("approved_size"),
                data.get("approved_entry"),
                data.get("approved_stop"),
                data.get("approved_target"),
                data.get("execution_venue", ""),
                data.get("reasoning", ""),
                json.dumps(data),
            ))
            conn.commit()

    def record_trade_outcome(self, symbol: str, entry: float, exit_price: float,
                              pnl: float, pnl_pct: float, exit_reason: str):
        """Record the outcome of a trade after it closes."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trade_outcomes
                (timestamp, symbol, entry_price, exit_price, pnl, pnl_pct, exit_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (self._now(), symbol, entry, exit_price, pnl, pnl_pct, exit_reason))
            conn.commit()

    def get_reports_for_symbol(self, symbol: str, days: int = 7) -> List[Dict]:
        """Get analyst reports for a symbol in the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM analyst_reports WHERE symbol = ? AND timestamp > ? ORDER BY timestamp DESC",
                (symbol, cutoff)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_decisions(self, verdict: Optional[str] = None, days: int = 30) -> List[Dict]:
        """Get final decisions, optionally filtered by verdict."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            if verdict:
                rows = conn.execute(
                    "SELECT * FROM final_decisions WHERE verdict = ? AND timestamp > ? ORDER BY timestamp DESC",
                    (verdict, cutoff)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM final_decisions WHERE timestamp > ? ORDER BY timestamp DESC",
                    (cutoff,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get trading statistics for the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM final_decisions WHERE timestamp > ?", (cutoff,)
            ).fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM final_decisions WHERE verdict = 'approve' AND timestamp > ?", (cutoff,)
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM final_decisions WHERE verdict = 'reject' AND timestamp > ?", (cutoff,)
            ).fetchone()[0]
            outcomes = conn.execute(
                "SELECT COUNT(*), SUM(pnl), AVG(pnl) FROM trade_outcomes WHERE timestamp > ?", (cutoff,)
            ).fetchone()

        return {
            "total_decisions": total,
            "approved": approved,
            "rejected": rejected,
            "approval_rate": approved / total if total > 0 else 0,
            "trades_closed": outcomes[0] or 0,
            "total_pnl": round(outcomes[1] or 0, 2),
            "avg_pnl": round(outcomes[2] or 0, 2),
        }
