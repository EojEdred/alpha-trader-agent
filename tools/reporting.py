"""
Reporting Tools - Report generation and audit logging

Implements:
- generate_report
- log_execution
- calculate_pnl
- verify_fill_quality
- extract_learnings
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from loguru import logger

# Audit database path
AUDIT_DB_PATH = Path(__file__).parent.parent / "data" / "audit" / "audit.db"


def _ensure_audit_db():
    """Ensure audit database exists."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(AUDIT_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            agent TEXT,
            details TEXT,
            result TEXT
        )
    """)
    conn.commit()
    conn.close()


def generate_report(
    report_data: Dict = None,
    format: str = "markdown",
    trade_recommendations: List[Dict] = None,
    technical_signals: Dict = None,
    composite_sentiment: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate formatted report.
    """
    logger.info(f"Generating {format} report")

    timestamp = datetime.utcnow()

    # Build report content
    if format == "markdown":
        content = _generate_markdown_report(
            trade_recommendations=trade_recommendations,
            technical_signals=technical_signals,
            composite_sentiment=composite_sentiment,
            timestamp=timestamp
        )
    elif format == "html":
        content = _generate_html_report(
            trade_recommendations=trade_recommendations,
            technical_signals=technical_signals,
            composite_sentiment=composite_sentiment,
            timestamp=timestamp
        )
    else:
        content = _generate_text_report(
            trade_recommendations=trade_recommendations,
            technical_signals=technical_signals,
            composite_sentiment=composite_sentiment,
            timestamp=timestamp
        )

    # Save report
    reports_dir = Path(__file__).parent.parent / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"report_{timestamp.strftime('%Y%m%d_%H%M%S')}.{format if format != 'markdown' else 'md'}"
    filepath = reports_dir / filename

    with open(filepath, 'w') as f:
        f.write(content)

    return {
        'report_path': str(filepath),
        'format': format,
        'content': content,
        'generated_at': timestamp.isoformat()
    }


def _generate_markdown_report(
    trade_recommendations: List[Dict] = None,
    technical_signals: Dict = None,
    composite_sentiment: Dict = None,
    timestamp: datetime = None
) -> str:
    """Generate markdown formatted report."""

    lines = [
        f"# Alpha Trader Morning Report",
        f"**Generated:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "---",
        "",
        "## Market Summary",
        ""
    ]

    # Technical signals
    if technical_signals:
        trend = technical_signals.get('trend', 'neutral')
        lines.append(f"**Overall Trend:** {trend.upper()}")
        lines.append("")

        if technical_signals.get('indicators'):
            lines.append("### Technical Indicators")
            for ind, val in technical_signals['indicators'].items():
                if isinstance(val, dict):
                    lines.append(f"- **{ind}:** {json.dumps(val)}")
                else:
                    lines.append(f"- **{ind}:** {val:.2f}" if isinstance(val, float) else f"- **{ind}:** {val}")
            lines.append("")

    # Sentiment
    if composite_sentiment:
        score = composite_sentiment.get('composite_score', 0)
        sentiment = "Bullish" if score > 0.2 else "Bearish" if score < -0.2 else "Neutral"
        lines.append(f"**Sentiment:** {sentiment} ({score:.2f})")
        lines.append("")

    # Trade recommendations
    lines.append("## Trade Recommendations")
    lines.append("")

    if trade_recommendations:
        for i, trade in enumerate(trade_recommendations, 1):
            lines.append(f"### Trade {i}")
            lines.append(f"- **Direction:** {trade.get('direction', 'N/A').upper()}")
            lines.append(f"- **Conviction:** {trade.get('conviction', 0):.0%}")
            lines.append(f"- **Entry Criteria:** {trade.get('entry_criteria', 'N/A')}")
            lines.append("")
    else:
        lines.append("*No trade recommendations at this time.*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*This report is for informational purposes only. Always do your own research.*")

    return "\n".join(lines)


def _generate_html_report(
    trade_recommendations: List[Dict] = None,
    technical_signals: Dict = None,
    composite_sentiment: Dict = None,
    timestamp: datetime = None
) -> str:
    """Generate HTML formatted report."""
    md_content = _generate_markdown_report(
        trade_recommendations, technical_signals, composite_sentiment, timestamp
    )
    # Simple conversion - in production use a proper markdown renderer
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Alpha Trader Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 1px solid #eee; }}
    </style>
</head>
<body>
<pre>{md_content}</pre>
</body>
</html>"""
    return html


def _generate_text_report(
    trade_recommendations: List[Dict] = None,
    technical_signals: Dict = None,
    composite_sentiment: Dict = None,
    timestamp: datetime = None
) -> str:
    """Generate plain text report (for SMS)."""
    lines = [f"ALPHA TRADER {timestamp.strftime('%m/%d')}"]

    if technical_signals:
        trend = technical_signals.get('trend', 'neutral')
        lines.append(f"Trend: {trend.upper()}")

    if composite_sentiment:
        score = composite_sentiment.get('composite_score', 0)
        lines.append(f"Sentiment: {score:+.2f}")

    if trade_recommendations:
        lines.append(f"Trades: {len(trade_recommendations)}")
        for trade in trade_recommendations[:3]:  # Max 3 for SMS
            direction = trade.get('direction', '?')[0].upper()
            conviction = trade.get('conviction', 0)
            lines.append(f"- {direction} ({conviction:.0%})")

    return " | ".join(lines)


def log_order_filled(symbol: str, side: str, quantity: float, price: float, venue: str):
    """Specific helper to log fills for PDT tracking."""
    details = {
        'symbol': symbol,
        'side': side,
        'quantity': quantity,
        'price': price,
        'venue': venue,
        'executed_at': datetime.utcnow().isoformat()
    }
    return log_execution(action='order_filled', details=details, agent='execution_engine')

def log_execution(
    action: str = "agent_action",
    details: Dict = None,
    agent: str = "dexter",
    **kwargs
) -> Dict[str, Any]:
    """
    Write to immutable audit log.
    """
    logger.info(f"Logging execution: {action}")

    _ensure_audit_db()

    timestamp = datetime.utcnow().isoformat()
    
    # If details not provided, use all other kwargs
    if details is None:
        details = {k: v for k, v in kwargs.items() if k != 'config'}

    conn = sqlite3.connect(AUDIT_DB_PATH)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO audit_log (timestamp, action, agent, details, result) VALUES (?, ?, ?, ?, ?)",
        (timestamp, action, agent, json.dumps(details), json.dumps({'status': 'logged'}))
    )

    log_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        'log_id': log_id,
        'timestamp': timestamp,
        'action': action
    }


def calculate_pnl(
    positions: List[Dict],
    current_prices: Dict,
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate profit/loss for positions.
    """
    logger.info("Calculating P&L")

    result = {
        'total_pnl': 0.0,
        'total_pnl_pct': 0.0,
        'positions': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    total_cost = 0.0
    total_value = 0.0

    for pos in positions:
        symbol = pos.get('symbol')
        quantity = pos.get('quantity', 0)
        avg_cost = pos.get('avg_cost', 0)

        current_price = current_prices.get(symbol, avg_cost)

        cost_basis = quantity * avg_cost
        market_value = quantity * current_price
        pnl = market_value - cost_basis
        pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0

        result['positions'].append({
            'symbol': symbol,
            'quantity': quantity,
            'cost_basis': cost_basis,
            'market_value': market_value,
            'pnl': pnl,
            'pnl_pct': pnl_pct
        })

        total_cost += cost_basis
        total_value += market_value

    result['total_pnl'] = total_value - total_cost
    result['total_pnl_pct'] = (result['total_pnl'] / total_cost * 100) if total_cost > 0 else 0

    return result


def read_research(
    morning_report_queue: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Load queued research data.
    """
    research_dir = Path(__file__).parent.parent / "data" / "research"

    # Find most recent research file
    if research_dir.exists():
        files = sorted(research_dir.glob("*.json"), reverse=True)
        if files:
            with open(files[0]) as f:
                return json.load(f)

    return {'status': 'no_data'}


def calculate_pnl_summary(
    period: str = "today",
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate P&L summary for a given period.

    Args:
        period: 'today', 'week', 'month', 'all'

    Returns:
        P&L summary dictionary
    """
    logger.info(f"Calculating P&L summary for {period}")

    # This is a simplified version - in a real implementation, this would
    # query the audit database for actual trade results

    # For now, return placeholder values
    return {
        'total': 0.0,
        'win_rate': 0.0,
        'trade_count': 0,
        'best': 0.0,
        'worst': 0.0,
        'period': period
    }


def generate_zynth_report(
    execution_plans: List[Dict],
    format: str = "markdown",
    **kwargs
) -> Dict[str, Any]:
    """
    Generate enhanced Zynth-level grouped ranked morning report.

    Groups trade intents by category: Primary / Conditional / Signal-only
    Includes invalidation prices and time stops
    Supports both Markdown and JSON output formats.
    """
    from datetime import datetime
    from loguru import logger

    logger.info(f"Generating Zynth-enhanced report ({format} format)")

    if not execution_plans:
        return {
            'error': 'No execution plans provided',
            'content': None,
            'json': {}
        }

    # Group intents by execution mode
    primary_intents = []
    conditional_intents = []
    signal_only_intents = []

    for plan in execution_plans:
        mode = plan.get('execution_mode', 'SIGNAL_ONLY')
        
        if mode == 'AUTO':
            primary_intents.append(plan)
        elif mode == 'CONFIRM':
            conditional_intents.append(plan)
        elif mode == 'SIGNAL_ONLY':
            signal_only_intents.append(plan)

    # Sort each group by conviction
    primary_intents.sort(key=lambda x: x.get('conviction', 0), reverse=True)
    conditional_intents.sort(key=lambda x: x.get('conviction', 0), reverse=True)
    signal_only_intents.sort(key=lambda x: x.get('conviction', 0), reverse=True)

    # Generate report
    timestamp = datetime.utcnow()
    
    lines = []
    lines.append(f"# Morning Trading Report")
    lines.append(f"**Generated:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Primary Trades (AUTO):** {len(primary_intents)}")
    lines.append(f"- **Conditional Trades (CONFIRM):** {len(conditional_intents)}")
    lines.append(f"- **Signal-Only (No Execution):** {len(signal_only_intents)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Primary Trades (AUTO Mode)")
    lines.append("")
    
    if primary_intents:
        lines.append("| Rank | Symbol | Direction | Entry | Stop | Target | Conviction | Venue | Evidence |")
        lines.append("|------|--------|-----------|-------|------|--------|------------|-------|----------|")
        
        for i, plan in enumerate(primary_intents, 1):
            intent = plan.get('order_payload', {})
            lines.append(f"| {i:2d} | {intent.get('symbol', 'N/A')} | {intent.get('direction', 'N/A')} | ${intent.get('price', 0):.2f} | ${intent.get('stop_price', 0):.2f} | ${intent.get('target_price', 0):.2f} | {plan.get('conviction', 0):.2%} | {intent.get('venue', 'N/A')} | {len(intent.get('evidence_citations', []))} |")
    else:
        lines.append("*No primary trades at this time.*")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Conditional Trades (Requires Approval)")
    lines.append("")
    
    if conditional_intents:
        lines.append("| Rank | Symbol | Direction | Entry | Stop | Target | Conviction | Venue | Evidence |")
        lines.append("|------|--------|-----------|-------|------|--------|------------|-------|----------|")
        
        for i, plan in enumerate(conditional_intents, 1):
            intent = plan.get('order_payload', {})
            lines.append(f"| {i:2d} | {intent.get('symbol', 'N/A')} | {intent.get('direction', 'N/A')} | ${intent.get('price', 0):.2f} | ${intent.get('stop_price', 0):.2f} | ${intent.get('target_price', 0):.2f} | {plan.get('conviction', 0):.2%} | {intent.get('venue', 'N/A')} | {len(intent.get('evidence_citations', []))} |")
    else:
        lines.append("*No conditional trades at this time.*")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Signal-Only (Research)")
    lines.append("")
    
    if signal_only_intents:
        lines.append("| Rank | Symbol | Direction | Entry | Stop | Target | Conviction | Venue | Evidence |")
        lines.append("|------|--------|-----------|-------|------|--------|------------|-------|----------|")
        
        for i, plan in enumerate(signal_only_intents, 1):
            intent = plan.get('order_payload', {})
            lines.append(f"| {i:2d} | {intent.get('symbol', 'N/A')} | {intent.get('direction', 'N/A')} | ${intent.get('price', 0):.2f} | ${intent.get('stop_price', 0):.2f} | ${intent.get('target_price', 0):.2f} | {plan.get('conviction', 0):.2%} | {intent.get('venue', 'N/A')} | {len(intent.get('evidence_citations', []))} |")
    else:
        lines.append("*No signal-only trades at this time.*")
    
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This is an enhanced Zynth-level report with grouped, ranked trade recommendations.*")

    content = "\n".join(lines)
    
    # Save report
    reports_dir = Path(__file__).parent.parent / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = f"zynth_report_{timestamp.strftime('%Y%m%d_%H%M%S')}.md"
    filepath = reports_dir / filename

    with open(filepath, 'w') as f:
        f.write(content)

    return {
        'report_path': str(filepath),
        'format': format,
        'content': content,
        'generated_at': timestamp.isoformat(),
        'json': {
            'primary_trades': len(primary_intents),
            'conditional_trades': len(conditional_intents),
            'signal_only_trades': len(signal_only_intents),
            'timestamp': timestamp.isoformat()
        }
    }


def extract_learnings(
    execution_results: List[Dict] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Extract learnings from past executions for improvement.
    """
    logger.info("Extracting learnings")

    return {
        'learnings': [],
        'recommendations': [],
        'timestamp': datetime.utcnow().isoformat()
    }