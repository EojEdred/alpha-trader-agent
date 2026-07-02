"""
Daily Trading Review & Learning Report

Generates a comprehensive end-of-day report covering:
- All trades taken (entries, exits, P&L)
- System errors and issues
- Open positions carried overnight
- Performance metrics
- Lessons learned and parameter suggestions

Runs automatically at 4:35 PM ET via scheduler.
"""

import os
import re
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger

AUDIT_DB_PATH = Path(__file__).parent.parent / "data" / "audit" / "audit.db"
REPORTS_DIR = Path(__file__).parent.parent / "data" / "reports" / "daily"
LOGS_DIR = Path(__file__).parent.parent / "logs"
STATE_PATH = Path("/Users/macbook/.alphatrader/data/options_position_state.json")

ET = __import__('pytz').timezone('America/New_York') if 'pytz' in __import__('sys').modules else None


def _et_today() -> str:
    """Return today's date in ET."""
    if ET:
        return datetime.now(ET).strftime("%Y-%m-%d")
    return datetime.utcnow().strftime("%Y-%m-%d")


def _et_yesterday() -> str:
    """Return yesterday's date in ET."""
    if ET:
        return (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d")
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")


def _get_today_from_ts(ts: str) -> str:
    """Extract date portion from ISO timestamp."""
    return ts[:10] if ts and len(ts) >= 10 else ""


def fetch_todays_trades() -> List[Dict]:
    """Fetch all trades from audit DB for today."""
    today = _et_today()
    if not AUDIT_DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(AUDIT_DB_PATH)
    cursor = conn.cursor()
    
    # Check if trades table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
    if not cursor.fetchone():
        conn.close()
        return []
    
    rows = cursor.execute(
        "SELECT * FROM trades WHERE timestamp LIKE ? ORDER BY timestamp",
        (f"{today}%",)
    ).fetchall()
    
    cols = [d[0] for d in cursor.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def fetch_todays_errors() -> List[str]:
    """Fetch error lines from today's logs."""
    today = _et_today()
    errors = []
    
    # Check main log files
    for log_file in sorted(LOGS_DIR.glob("alpha_trader*.log"), reverse=True)[:3]:
        try:
            with open(log_file, "r", errors="ignore") as f:
                for line in f:
                    # Check if line is from today
                    if today in line or (len(line) > 20 and line[:10] == today):
                        if any(k in line.lower() for k in ["error", "failed", "crash", "exception", "unexpected keyword", "got an unexpected"]):
                            errors.append(line.strip()[:300])
        except Exception:
            pass
    
    # Also check scheduler log
    scheduler_log = LOGS_DIR / "scheduler.log"
    if scheduler_log.exists():
        try:
            with open(scheduler_log, "r", errors="ignore") as f:
                for line in f:
                    if today in line or (len(line) > 20 and line[:10] == today):
                        if any(k in line.lower() for k in ["error", "failed", "exception"]):
                            errors.append(f"[scheduler] {line.strip()[:300]}")
        except Exception:
            pass
    
    return list(dict.fromkeys(errors))[:50]  # Deduplicate, limit 50


def fetch_brain_decisions() -> List[Dict]:
    """Fetch today's brain decisions from audit log."""
    today = _et_today()
    if not AUDIT_DB_PATH.exists():
        return []
    
    conn = sqlite3.connect(AUDIT_DB_PATH)
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT timestamp, action, details FROM audit_log WHERE action = ? AND timestamp LIKE ? ORDER BY timestamp",
        ("agent_action", f"{today}%")
    ).fetchall()
    conn.close()
    
    decisions = []
    for ts, action, details_json in rows:
        try:
            details = json.loads(details_json)
            brain = details.get("brain_decision", {})
            if brain and brain.get("direction") != "none":
                decisions.append({
                    "timestamp": ts,
                    "symbol": brain.get("symbol") or brain.get("underlying", "unknown"),
                    "direction": brain.get("direction"),
                    "score": brain.get("score", 0),
                    "thesis": brain.get("thesis", "")[:100],
                })
        except Exception:
            pass
    return decisions


def fetch_open_positions() -> List[Dict]:
    """Fetch currently open option positions from state file."""
    if not STATE_PATH.exists():
        return []
    try:
        with open(STATE_PATH, "r") as f:
            state = json.load(f)
        return [{"symbol": k, **v} for k, v in state.items()]
    except Exception:
        return []


def calculate_pnl_summary(trades: List[Dict]) -> Dict[str, Any]:
    """Calculate P&L summary from trades."""
    entries = [t for t in trades if "buy" in t.get("side", "").lower()]
    exits = [t for t in trades if "sell" in t.get("side", "").lower()]
    
    total_pnl = sum(t.get("pnl", 0) or 0 for t in exits)
    winning_exits = [t for t in exits if (t.get("pnl") or 0) > 0]
    losing_exits = [t for t in exits if (t.get("pnl") or 0) < 0]
    
    win_rate = len(winning_exits) / len(exits) * 100 if exits else 0
    avg_win = sum(t.get("pnl", 0) for t in winning_exits) / len(winning_exits) if winning_exits else 0
    avg_loss = sum(t.get("pnl", 0) for t in losing_exits) / len(losing_exits) if losing_exits else 0
    
    # Group by venue
    venue_pnl = {}
    for t in exits:
        v = t.get("venue", "unknown")
        venue_pnl[v] = venue_pnl.get(v, 0) + (t.get("pnl", 0) or 0)
    
    return {
        "total_pnl": round(total_pnl, 2),
        "total_trades": len(entries),
        "total_exits": len(exits),
        "win_rate": round(win_rate, 1),
        "winning_trades": len(winning_exits),
        "losing_trades": len(losing_exits),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "venue_pnl": venue_pnl,
    }


def generate_daily_review() -> str:
    """Generate the full daily review markdown report."""
    today = _et_today()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    
    trades = fetch_todays_trades()
    errors = fetch_todays_errors()
    brain_decisions = fetch_brain_decisions()
    open_positions = fetch_open_positions()
    pnl = calculate_pnl_summary(trades)
    
    report = f"""# 📊 Daily Trading Review — {today}
**Generated:** {now}

---

## 💰 P&L Summary

| Metric | Value |
|--------|-------|
| **Total Realized P&L** | ${pnl['total_pnl']:.2f} |
| **Total Entries** | {pnl['total_trades']} |
| **Total Exits** | {pnl['total_exits']} |
| **Win Rate** | {pnl['win_rate']:.1f}% ({pnl['winning_trades']}W / {pnl['losing_trades']}L) |
| **Avg Win** | ${pnl['avg_win']:.2f} |
| **Avg Loss** | ${pnl['avg_loss']:.2f} |

**By Venue:**
"""
    for venue, v_pnl in pnl["venue_pnl"].items():
        emoji = "🟢" if v_pnl >= 0 else "🔴"
        report += f"- {emoji} **{venue.title()}:** ${v_pnl:.2f}\n"
    
    if not pnl["venue_pnl"]:
        report += "- No realized P&L today.\n"
    
    report += "\n---\n\n## 📈 Trades Log\n\n"
    if trades:
        report += "| Time | Venue | Symbol | Side | Qty | Price | P&L | Status |\n"
        report += "|------|-------|--------|------|-----|-------|-----|--------|\n"
        for t in trades:
            ts = t.get("timestamp", "")[11:19] if t.get("timestamp") else ""
            report += f"| {ts} | {t.get('venue','')} | {t.get('symbol','')} | {t.get('side','')} | {t.get('quantity','')} | {t.get('price') or '-'} | {t.get('pnl') or '-'} | {t.get('status','')} |\n"
    else:
        report += "*No trades logged today.*\n"
    
    report += "\n---\n\n## 🧠 Brain Decisions\n\n"
    if brain_decisions:
        report += "| Time | Symbol | Direction | Score | Thesis |\n"
        report += "|------|--------|-----------|-------|--------|\n"
        for d in brain_decisions[-20:]:  # Last 20
            ts = d.get("timestamp", "")[11:19] if d.get("timestamp") else ""
            report += f"| {ts} | {d['symbol']} | {d['direction']} | {d['score']} | {d['thesis']} |\n"
    else:
        report += "*No brain decisions recorded today.*\n"
    
    report += "\n---\n\n## 📂 Open Positions (Carried Overnight)\n\n"
    if open_positions:
        for pos in open_positions:
            report += f"- **{pos.get('symbol', 'unknown')}**: {pos.get('current_contracts', 0)} contracts @ avg {pos.get('average_entry', 0)}\n"
            report += f"  - Highest P&L: ${pos.get('highest_unrealized_pl', 0):.2f}\n"
            report += f"  - Tiers hit: T1={pos.get('tier_1_done', False)} T2={pos.get('tier_2_done', False)} T3={pos.get('tier_3_done', False)}\n"
    else:
        report += "*No open positions.*\n"
    
    report += "\n---\n\n## ⚠️ System Errors & Issues\n\n"
    if errors:
        report += "```\n"
        for err in errors[:30]:
            report += f"{err}\n"
        report += "```\n"
    else:
        report += "*No errors logged today.*\n"
    
    report += "\n---\n\n## 📝 Lessons & Adjustments\n\n"
    
    # Auto-generate lessons based on data
    lessons = []
    
    if errors:
        kwarg_errors = [e for e in errors if "unexpected keyword argument" in e.lower()]
        if kwarg_errors:
            lessons.append("🔧 **System Bug:** Functions crashed due to missing `**kwargs`. Ensure all tool wrappers accept `**kwargs` — this caused missed exits today.")
    
    if pnl["total_exits"] == 0 and pnl["total_trades"] > 0:
        lessons.append("🚨 **Exit Failure:** Positions were entered but no exits recorded. Check profit-locking engine and position monitor workflow.")
    
    if pnl["win_rate"] > 0 and pnl["win_rate"] < 40 and pnl["total_exits"] >= 3:
        lessons.append("📉 **Low Win Rate:** Win rate below 40%. Consider tightening entry criteria or reducing position size.")
    
    if pnl["avg_loss"] < -50 and pnl["avg_win"] < 50:
        lessons.append("⚖️ **Risk/Reward Imbalance:** Avg loss larger than avg win. Review stop_loss placement — stops may be too wide or targets too tight.")
    
    if not brain_decisions:
        lessons.append("🧠 **No Brain Signals:** No trade decisions generated. Check market data feed and brain prompt configuration.")
    elif len([d for d in brain_decisions if d["score"] > 45]) == 0 and len(brain_decisions) > 5:
        lessons.append("🎯 **Low Scores:** Brain returned no scores above threshold. Market may be choppy, or threshold may be too high for current conditions.")
    
    if open_positions:
        lessons.append("🌙 **Overnight Risk:** Positions held overnight. 0DTE options will gap at open. Monitor pre-market for exit opportunity.")
    
    if not lessons:
        lessons.append("✅ **Clean Session:** No major issues detected. Continue current parameters.")
    
    for lesson in lessons:
        report += f"- {lesson}\n"
    
    report += "\n---\n\n## 🔧 Suggested Parameter Adjustments\n\n"
    
    suggestions = []
    if pnl["win_rate"] > 60 and pnl["avg_win"] > 80:
        suggestions.append("Winners are running well. Consider increasing Tier 4 trail from 15% to 20% to capture larger moves.")
    if pnl["win_rate"] < 30 and pnl["total_exits"] >= 5:
        suggestions.append("Too many losers. Tighten entry score threshold from 45 to 50, or reduce max hold time from 15 to 10 minutes.")
    if pnl["avg_loss"] < -80:
        suggestions.append("Losses too large. Consider reducing hard stop from -$100 to -$75, or tighten original stop from 20% to 15% of premium.")
    if not suggestions:
        suggestions.append("No parameter changes suggested based on today's data.")
    
    for s in suggestions:
        report += f"- {s}\n"
    
    report += f"""

---

*Report generated by AlphaTrader Daily Review Engine*
*Next review: {today} 16:35 ET*
"""
    return report


def save_and_notify(report: str):
    """Save report to disk and send Telegram notification."""
    today = _et_today()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    report_path = REPORTS_DIR / f"review_{today}.md"
    with open(report_path, "w") as f:
        f.write(report)
    
    logger.info(f"Daily review saved to {report_path}")
    
    # Send Telegram summary
    try:
        from tools.delivery import send_telegram
        summary = f"📊 Daily Review: {today}\n"
        trades = fetch_todays_trades()
        pnl = calculate_pnl_summary(trades)
        summary += f"P&L: ${pnl['total_pnl']:.2f} | Trades: {pnl['total_trades']} | Win Rate: {pnl['win_rate']:.0f}%\n"
        errors = fetch_todays_errors()
        if errors:
            summary += f"⚠️ {len(errors)} errors today. Check report.\n"
        send_telegram(summary)
    except Exception as e:
        logger.debug(f"Telegram notification failed: {e}")


async def run_daily_review(**kwargs):
    """Entry point for scheduler / workflow."""
    logger.info("📊 Generating daily trading review...")
    report = generate_daily_review()
    save_and_notify(report)
    return {"status": "ok", "report_path": str(REPORTS_DIR / f"review_{_et_today()}.md")}


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_daily_review())
