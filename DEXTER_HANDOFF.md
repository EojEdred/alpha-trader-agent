# DEXTER CLI Integration - Complete Handoff Document

> **Date:** January 4, 2026
> **Status:** Architecture Complete, Ready for Implementation
> **Location:** `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/`
> **Handoff To:** Next Terminal Session

---

## Table of Contents

1. [What Exists (Alpha Trader)](#1-what-exists-alpha-trader)
2. [What Dexter Adds](#2-what-dexter-adds)
3. [Eoj's Trading Strategy (From Prior Work)](#3-eojs-trading-strategy)
4. [Unified Architecture](#4-unified-architecture)
5. [Implementation Guide](#5-implementation-guide)
6. [Full Code for New Modules](#6-full-code-for-new-modules)
7. [Execution Matrix](#7-execution-matrix)
8. [Build Order](#8-build-order)

---

## 1. What Exists (Alpha Trader)

### Current Directory Structure
```
/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/
├── ALPHA_TRADER_HANDOFF.md      # Original handoff (500+ lines)
├── agent_templates.yaml          # 5 agents defined
├── config/
│   └── config.yaml              # Risk limits, watchlists
├── workflows/
│   ├── daily_research_cycle.yaml
│   ├── morning_report.yaml
│   ├── trade_execution.yaml
│   └── continuous_monitoring.yaml
├── tools/
│   ├── tool_registry.yaml       # 25+ tools
│   ├── market_data.py           # CCXT, Polymarket, basic fetchers
│   ├── analysis.py              # Basic technicals (SMA, RSI, MACD)
│   ├── strategy.py              # Position sizing, risk eval
│   ├── execution.py             # IB adapter (placeholder)
│   ├── reporting.py             # Report generation, audit log
│   ├── delivery.py              # Email/SMS via SendGrid/Twilio
│   └── __init__.py
├── standalone/
│   ├── main.py                  # Entry point
│   ├── scheduler.py             # APScheduler (4 AM, 6 AM, 5-min)
│   ├── orchestrator.py          # Workflow DAG executor
│   ├── config.py                # Config loader
│   ├── requirements.txt
│   └── __init__.py
└── data/
    ├── research/
    ├── reports/
    ├── audit/
    └── positions/
```

### What Alpha Trader Does Now
- Scheduled workflows (4 AM research, 6 AM report, 5-min monitoring)
- Basic technical analysis (SMA, RSI, MACD)
- Crypto data via CCXT
- Polymarket data fetching
- Report generation (markdown, HTML, text)
- Audit logging to SQLite
- Email/SMS delivery

### What Alpha Trader LACKS
- **No CLI** (just `python main.py`)
- **No Volume Profile** (core strategy)
- **No Order Flow** (CVD, delta, footprint)
- **No A+ Scoring System** (deterministic trade grading)
- **No Arbitrage Scanner** (prediction market arbs)
- **No OANDA adapter** (for gold execution)
- **No Kalshi adapter** (for regulated prediction markets)
- **No Trade State Machine** (lifecycle tracking)
- **No Rich terminal output** (photo-card style)

---

## 2. What Dexter Adds

### Dexter Core Concept
```
Dexter = Typer CLI + Rich TUI + Research Agents + Deterministic Scoring + Report Renderer
```

### Dexter Pipeline
```
INGEST → EXTRACT → ANALYZE → SYNTHESIZE → RENDER → DELIVER
  │         │         │          │          │         │
  │         │         │          │          │         └── File/Email/Discord/Slack
  │         │         │          │          └── Terminal + Markdown + PDF
  │         │         │          └── Trade Objects (standardized schema)
  │         │         └── Volume Profile + Order Flow + A+ Score
  │         └── trafilatura (web) + LlamaIndex (RAG)
  └── OANDA + Kalshi + Polymarket + Schwab* + Polygon
```

### Dexter Tech Stack
```yaml
cli_layer:
  - typer              # CLI framework (dexter run, dexter brief, etc.)
  - rich               # Terminal tables, panels, progress bars
  - textual            # Optional TUI dashboard

research_layer:
  - trafilatura        # Web content extraction (clean HTML → text)
  - llama-index        # Document indexing + RAG memory

analytics_layer:
  - py_vollib          # Options IV + Greeks calculation
  - optionlab          # Strategy payoff diagrams
  - vectorbt           # Fast backtesting

execution_layer:
  - oandapyV20         # OANDA REST API (gold - AUTO now)
  - aiokalshi          # Kalshi async client (AUTO now)
  - py-clob-client     # Polymarket CLOB (AUTO now)
  - schwab-py          # Schwab (SIGNAL_ONLY until approved)
```

### Dexter CLI Commands
```bash
dexter run                    # Start full scheduler
dexter brief                  # Generate morning brief now
dexter brief --date 2026-01-03  # Generate for specific date
dexter score SYMBOL           # Score a specific setup
dexter arb                    # Run arbitrage scanner
dexter arb --execute          # Execute detected arbs
dexter trade SYMBOL long      # Manual trade entry
dexter positions              # Show current positions
dexter pnl                    # Show P&L
dexter watch                  # Live TUI dashboard
dexter backtest STRATEGY      # Run backtest
```

---

## 3. Eoj's Trading Strategy (From Prior Work)

### Source File
`/Users/macbook/Desktop/Finance/Trading-Folder/Autonomous Trading Agent Framework/trading-system-outlines.md`

### Volume Profile Strategy (FVA Scalper)

**Core Concept:** Trade from high-probability locations using volume profile analysis.

```
Volume Profile Components:
├── Session Profile: Distribution of volume across price levels
├── Point of Control (POC): Price with highest volume
├── Value Area (VA): 70% of volume centered on POC
├── Fair Value Area (FVA): 40% of volume (tighter zone)
├── High Volume Nodes (HVN): Price clusters with high activity
└── Low Volume Nodes (LVN): Price gaps with low activity (fast moves)
```

**Trade Locations (in priority order):**
1. **POC Bounce:** Price touches POC, order flow confirms, trade the bounce
2. **FVA Edge:** Price at 40% FVA boundary with rejection
3. **LVN Breakout:** Fast move through LVN to next HVN
4. **HVN Fade:** Price stalls at HVN, reversal setup

### Order Flow Confirmation

**CVD (Cumulative Volume Delta):**
```
CVD = Σ(Buy Volume - Sell Volume)

Signals:
├── Extreme Delta: CVD spikes to session high/low
├── Divergence: Price makes new high, CVD doesn't (or vice versa)
└── Exhaustion: CVD flattens while price continues
```

**Footprint Signals:**
```
├── Absorption: Large orders absorbed without price movement
├── Failed Imbalance: Imbalance candle fails to follow through
└── One-Sided Failure: All buying/selling but price reverses
```

### A+ Scoring System

**Deterministic scoring rubric (0-100 points):**

| Component | Points | Criteria |
|-----------|--------|----------|
| **Location** | 0-25 | At POC (25), FVA edge (20), HVN (15), random (0) |
| **Order Flow** | 0-25 | CVD confirms (15), footprint signal (10), volume expansion (5) |
| **Setup Quality** | 0-25 | Clean setup (25), minor issues (15), forced (0) |
| **Regime Alignment** | 0-25 | Trend + vol favorable (25), neutral (15), against (0) |

**Grade Thresholds:**
```
A+ (85-100): Full size, high conviction
A  (75-84):  Full size, normal conviction
B  (60-74):  50% size, reduced conviction
C  (<60):    NO TRADE
```

### Three Core Setups

**Setup 1: POC Bounce**
```
Conditions:
- Price within 2 ticks of POC
- CVD showing exhaustion or divergence
- Footprint shows absorption
- Volume declining on approach

Entry: Limit at POC
Stop: 2 ticks beyond POC (structural)
Target 1: Nearest HVN (50% position)
Target 2: FVA edge (runner)
```

**Setup 2: FVA Edge Fade**
```
Conditions:
- Price at 40% FVA boundary
- Rejection candle forming
- CVD divergence
- Below-average volume

Entry: Limit at FVA edge after rejection
Stop: Beyond FVA edge + buffer
Target 1: POC
Target 2: Opposite FVA edge
```

**Setup 3: LVN Breakout**
```
Conditions:
- Price breaking through LVN
- Volume expansion (1.5x+ average)
- CVD confirming direction
- Clean LVN (minimal structure)

Entry: Stop order beyond LVN
Stop: Back inside LVN
Target 1: Next HVN
Target 2: Next POC
```

### Prediction Market Arbitrage

**Type A: Sum Arbitrage (Single Platform)**
```python
if polymarket_yes + polymarket_no < 0.995:  # After fees
    profit = 1.00 - (yes_price + no_price)
    if profit > 0.005:  # 0.5% minimum
        buy_yes(size)
        buy_no(size)
```

**Type B: Cross-Platform Arbitrage**
```python
# Same event on Polymarket and Kalshi
if polymarket_yes + kalshi_no < 0.985:  # Higher threshold
    profit = 1.00 - (poly_yes + kalshi_no)
    if profit > 0.015:  # 1.5% minimum
        buy_polymarket_yes(size)
        buy_kalshi_no(size)
```

**Type C: Multi-Outcome Arbitrage**
```python
# Multi-outcome event (e.g., "Who wins election?")
outcome_sum = sum(all_outcome_prices)
if outcome_sum < 0.97:  # 3% spread
    for outcome in outcomes:
        buy_outcome(size * (1 / len(outcomes)))
```

### Risk Rules

```yaml
risk_rules:
  max_trades_per_day: 5
  max_loss_per_day_pct: 2.0
  max_loss_per_trade_pct: 0.5
  max_position_pct: 5.0

  grade_sizing:
    A_PLUS: 1.0    # Full size
    A: 1.0         # Full size
    B: 0.5         # Half size
    C: 0.0         # No trade

  circuit_breakers:
    consecutive_losses: 2      # Pause after 2 losses
    daily_loss_pct: 2.0        # Stop for day
    weekly_loss_pct: 5.0       # Reduce size next week

  prohibited_windows:
    - "FOMC"
    - "CPI"
    - "NFP"
    - "30min_before_close"
```

### Trade State Machine

```
IDLE
  │
  ▼
SCANNING ──────────────────────────────────────┐
  │                                            │
  ▼                                            │
LOCATION_VALID (price at POC/FVA/HVN/LVN)     │
  │                                            │
  ▼                                            │
FLOW_QUALIFIED (CVD/delta/footprint confirm)   │
  │                                            │
  ▼                                            │
SETUP_MATCHED (Setup 1, 2, or 3)              │
  │                                            │
  ▼                                            │
SCORED (A+/A/B/C grade assigned)              │
  │                                            │
  ├── Grade C ─────────────────────────────────┘
  │
  ▼
EXECUTING (order placed)
  │
  ▼
MANAGING (position open, stops/targets active)
  │
  ▼
CLOSED (position flat, logged)
  │
  └──────────────────────────────────────────► IDLE
```

---

## 4. Unified Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              DEXTER CLI (Typer + Rich)                           │
│                                                                                  │
│  dexter run | dexter brief | dexter score | dexter arb | dexter trade | watch   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           MARKET DATA LAYER                                      │
│                                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │  FUTURES   │ │  OPTIONS   │ │ PREDICTION │ │   FOREX    │ │    NEWS    │   │
│  │  NQ/ES/GC  │ │  SPY/QQQ   │ │  MARKETS   │ │   XAUUSD   │ │  + WEB     │   │
│  │            │ │            │ │            │ │            │ │            │   │
│  │ • Polygon  │ │ • Polygon  │ │ • Polymar. │ │ • OANDA    │ │ • trafila. │   │
│  │ • Rithmic* │ │ • Schwab*  │ │ • Kalshi   │ │   v20 API  │ │ • NewsAPI  │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
│                                                                                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           FEATURE LAYER                                          │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                      VOLUME PROFILE ENGINE                               │   │
│  │                                                                          │   │
│  │  calculate_session_profile() → calculate_40_fva() → identify_poc()      │   │
│  │  detect_hvn() → detect_lvn() → get_trade_location()                     │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       ORDER FLOW ENGINE                                  │   │
│  │                                                                          │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │   │
│  │  │ CVD Tracker  │  │   Volume     │  │  Footprint   │                  │   │
│  │  │              │  │  Analyzer    │  │   Reader     │                  │   │
│  │  │ • Cumulative │  │ • Session    │  │ • Absorption │                  │   │
│  │  │ • Extreme    │  │   Average    │  │ • Failed     │                  │   │
│  │  │ • Divergence │  │ • Expansion  │  │   Imbalance  │                  │   │
│  │  │ • Exhaustion │  │ • Climax     │  │ • One-sided  │                  │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                  │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       REGIME DETECTOR                                    │   │
│  │                                                                          │   │
│  │  vol_regime() → trend_state() → atr_bands() → expected_move()           │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           STRATEGY LAYER                                         │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       A+ SCORING ENGINE                                  │   │
│  │                                                                          │   │
│  │  Location      Order Flow    Setup         Regime         TOTAL         │   │
│  │  Validator  →  Qualifier  →  Classifier →  Checker    →   SCORE        │   │
│  │  (0-25 pts)    (0-25 pts)    (0-25 pts)    (0-25 pts)     (0-100)      │   │
│  │                                                                          │   │
│  │  A+ (85+) → Full Size | A (75-84) → Full | B (60-74) → Half | C → Skip │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       ARBITRAGE SCANNER                                  │   │
│  │                                                                          │   │
│  │  Market Matcher → Spread Calculator → Opportunity Ranker → Validator    │   │
│  │                                                                          │   │
│  │  Type A (sum): > 0.5% | Type B (cross): > 1.5% | Type C (multi): > 3%  │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           RISK GOVERNOR                                          │
│                                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐                   │
│  │   Daily    │ │    Loss    │ │  Session   │ │  Circuit   │                   │
│  │  Counter   │ │  Tracker   │ │   Timer    │ │  Breaker   │                   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘                   │
│                                                                                  │
│  Rules: Max 5 trades/day | Max 2% loss/day | No FOMC/CPI | 2-loss pause        │
│                                                                                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           EXECUTION ROUTER                                       │
│                                                                                  │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                 │
│  │      AUTO       │  │     CONFIRM     │  │   SIGNAL_ONLY   │                 │
│  │                 │  │                 │  │                 │                 │
│  │ • OANDA (gold)  │  │ • Large arbs    │  │ • NQ/ES/GC      │                 │
│  │ • Kalshi        │  │ • Options*      │  │ • Schwab*       │                 │
│  │ • Poly (small)  │  │                 │  │                 │                 │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘                 │
│                                                                                  │
│  State: IDLE → SCANNING → LOCATION_VALID → FLOW_QUALIFIED → SETUP_MATCHED →   │
│         SCORED → EXECUTING → MANAGING → CLOSED                                  │
│                                                                                  │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │
┌──────────────────────────────────────┴──────────────────────────────────────────┐
│                           BROKER ADAPTERS                                        │
│                                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │  OANDA   │ │  Kalshi  │ │Polymarket│ │ Schwab*  │ │ Polygon  │             │
│  │  v20 API │ │   API    │ │  CLOB    │ │   API    │ │  Data    │             │
│  │          │ │          │ │          │ │          │ │          │             │
│  │  XAUUSD  │ │ Regulated│ │  Crypto  │ │ Options  │ │  Market  │             │
│  │  AUTO    │ │  AUTO    │ │  AUTO    │ │ PENDING  │ │  Data    │             │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘             │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Implementation Guide

### Files to Create

```
alpha-trader/
├── cli.py                           # NEW: Typer CLI entry point
├── dexter/                          # NEW: Dexter package
│   ├── __init__.py
│   ├── cli.py                       # CLI commands
│   ├── tui.py                       # Rich/Textual dashboard
│   └── brief.py                     # Brief generator
├── tools/
│   ├── volume_profile.py            # NEW: Volume profile engine
│   ├── order_flow.py                # NEW: Order flow engine
│   ├── scoring.py                   # NEW: A+ scoring system
│   ├── arbitrage.py                 # NEW: Arb scanner
│   ├── oanda.py                     # NEW: OANDA adapter
│   ├── kalshi.py                    # NEW: Kalshi adapter
│   ├── polymarket.py                # NEW: Polymarket adapter (replace basic)
│   └── ... (existing files)
├── standalone/
│   ├── state_machine.py             # NEW: Trade state machine
│   └── ... (existing files)
└── config/
    └── config.yaml                  # UPDATE: Add new settings
```

### Updated requirements.txt

```txt
# Existing
pyyaml>=6.0
pydantic>=2.0
python-dotenv>=1.0
aiohttp>=3.9
aiosqlite>=0.19
apscheduler>=3.10
ccxt>=4.0
pandas>=2.0
numpy>=1.24
ta>=0.10.2
openai>=1.0
twilio>=8.0
sendgrid>=6.0
pytz>=2023.3
loguru>=0.7

# NEW - Dexter additions
typer>=0.9.0
rich>=13.0
textual>=0.40

# NEW - Research
trafilatura>=1.6
llama-index>=0.10

# NEW - Options analytics
py_vollib>=1.0.1

# NEW - Backtesting
vectorbt>=0.26

# NEW - Execution adapters
oandapyV20>=0.6.3
aiokalshi>=0.1
py-clob-client>=0.1
schwab-py>=0.1
```

---

## 6. Full Code for New Modules

### 6.1 CLI Entry Point (`cli.py`)

```python
#!/usr/bin/env python3
"""
Dexter CLI - Trading Research & Execution System

Usage:
    dexter run                    # Start scheduler
    dexter brief                  # Generate morning brief
    dexter score SYMBOL           # Score a setup
    dexter arb                    # Run arbitrage scanner
    dexter trade SYMBOL long      # Manual trade
    dexter positions              # Show positions
    dexter watch                  # Live dashboard
"""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from datetime import datetime
import asyncio

app = typer.Typer(name="dexter", help="Trading Research & Execution System")
console = Console()


@app.command()
def run():
    """Start the full scheduler (research, reports, monitoring)."""
    from standalone.main import AlphaTrader

    console.print(Panel.fit(
        "[bold green]DEXTER[/bold green] Trading System Starting...",
        title="🚀 Startup"
    ))

    trader = AlphaTrader()
    asyncio.run(trader.start())


@app.command()
def brief(
    date: str = typer.Option(None, help="Date for brief (YYYY-MM-DD)"),
    output: str = typer.Option("terminal", help="Output format: terminal, markdown, pdf")
):
    """Generate morning trading brief."""
    from dexter.brief import generate_brief

    target_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()

    console.print(f"\n[bold]Generating brief for {target_date.strftime('%Y-%m-%d')}...[/bold]\n")

    brief_data = asyncio.run(generate_brief(target_date))

    if output == "terminal":
        _display_brief_terminal(brief_data)
    else:
        console.print(f"Brief saved to: {brief_data['output_path']}")


@app.command()
def score(
    symbol: str = typer.Argument(..., help="Symbol to score (e.g., NQ, SPY)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed breakdown")
):
    """Score a trading setup using A+ system."""
    from tools.scoring import score_setup

    console.print(f"\n[bold]Scoring setup for {symbol}...[/bold]\n")

    result = asyncio.run(score_setup(symbol))

    # Display score card
    table = Table(title=f"A+ Score: {symbol}")
    table.add_column("Component", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")

    table.add_row("Location", str(result['location_pts']), "25")
    table.add_row("Order Flow", str(result['flow_pts']), "25")
    table.add_row("Setup Quality", str(result['setup_pts']), "25")
    table.add_row("Regime", str(result['regime_pts']), "25")
    table.add_row("─" * 15, "─" * 5, "─" * 5)
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{result['total']}[/bold]", "[bold]100[/bold]")

    console.print(table)

    grade = result['grade']
    grade_colors = {'A_PLUS': 'green', 'A': 'green', 'B': 'yellow', 'NO_TRADE': 'red'}
    console.print(f"\n[bold {grade_colors.get(grade, 'white')}]Grade: {grade}[/bold {grade_colors.get(grade, 'white')}]")

    if grade == 'NO_TRADE':
        console.print("[red]⚠️  Setup does not meet minimum criteria[/red]")
    elif grade == 'B':
        console.print("[yellow]📊 Trade at 50% size[/yellow]")
    else:
        console.print("[green]✅ Trade at full size[/green]")


@app.command()
def arb(
    execute: bool = typer.Option(False, "--execute", "-x", help="Execute detected arbs"),
    min_spread: float = typer.Option(1.0, help="Minimum spread % to show")
):
    """Scan for prediction market arbitrage opportunities."""
    from tools.arbitrage import scan_arbitrage

    console.print("\n[bold]Scanning for arbitrage opportunities...[/bold]\n")

    opportunities = asyncio.run(scan_arbitrage(min_spread_pct=min_spread))

    if not opportunities:
        console.print("[yellow]No arbitrage opportunities found above threshold.[/yellow]")
        return

    table = Table(title="Arbitrage Opportunities")
    table.add_column("Type", style="cyan")
    table.add_column("Market", style="white")
    table.add_column("Spread", justify="right", style="green")
    table.add_column("Platforms", style="white")
    table.add_column("Liquidity", justify="right")

    for opp in opportunities:
        table.add_row(
            opp['type'],
            opp['market'][:40],
            f"{opp['spread_pct']:.2f}%",
            opp['platforms'],
            f"${opp['liquidity']:,.0f}"
        )

    console.print(table)

    if execute:
        console.print("\n[bold yellow]Executing arbitrage trades...[/bold yellow]")
        # Execute logic here


@app.command()
def trade(
    symbol: str = typer.Argument(..., help="Symbol to trade"),
    direction: str = typer.Argument(..., help="long or short"),
    size: float = typer.Option(None, help="Position size (default: auto from scoring)"),
    venue: str = typer.Option("auto", help="Venue: auto, oanda, kalshi, polymarket")
):
    """Manually enter a trade."""
    from tools.execution import submit_trade

    console.print(f"\n[bold]Preparing {direction} trade for {symbol}...[/bold]\n")

    # First score the setup
    from tools.scoring import score_setup
    score_result = asyncio.run(score_setup(symbol))

    if score_result['grade'] == 'NO_TRADE':
        console.print("[red]⚠️  Setup scored below threshold. Trade anyway? (y/n)[/red]")
        confirm = typer.prompt("Confirm")
        if confirm.lower() != 'y':
            return

    result = asyncio.run(submit_trade(symbol, direction, size, venue))
    console.print(f"[green]Trade submitted: {result}[/green]")


@app.command()
def positions():
    """Show current open positions across all venues."""
    from tools.execution import get_all_positions

    positions = asyncio.run(get_all_positions())

    if not positions:
        console.print("[yellow]No open positions.[/yellow]")
        return

    table = Table(title="Open Positions")
    table.add_column("Venue", style="cyan")
    table.add_column("Symbol", style="white")
    table.add_column("Side", style="white")
    table.add_column("Size", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("P&L", justify="right")

    for pos in positions:
        pnl_color = "green" if pos['pnl'] >= 0 else "red"
        table.add_row(
            pos['venue'],
            pos['symbol'],
            pos['side'],
            str(pos['size']),
            f"{pos['entry']:.4f}",
            f"{pos['current']:.4f}",
            f"[{pnl_color}]{pos['pnl']:+.2f}[/{pnl_color}]"
        )

    console.print(table)


@app.command()
def pnl(
    period: str = typer.Option("today", help="Period: today, week, month, all")
):
    """Show P&L summary."""
    from tools.reporting import calculate_pnl_summary

    summary = asyncio.run(calculate_pnl_summary(period))

    console.print(Panel(
        f"""
[bold]P&L Summary ({period})[/bold]

Total P&L: [{'green' if summary['total'] >= 0 else 'red'}]{summary['total']:+.2f}[/]
Win Rate: {summary['win_rate']:.1%}
Trades: {summary['trade_count']}
Best: [green]+{summary['best']:.2f}[/green]
Worst: [red]{summary['worst']:.2f}[/red]
        """,
        title="📊 Performance"
    ))


@app.command()
def watch():
    """Launch live TUI dashboard."""
    from dexter.tui import DexterDashboard

    dashboard = DexterDashboard()
    dashboard.run()


@app.command()
def backtest(
    strategy: str = typer.Argument(..., help="Strategy to backtest"),
    start: str = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(None, help="End date (YYYY-MM-DD)")
):
    """Run backtest on historical data."""
    console.print(f"\n[bold]Running backtest for {strategy}...[/bold]\n")
    # Backtest implementation


def _display_brief_terminal(brief_data: dict):
    """Display brief in terminal with Rich formatting."""
    console.print(Panel(
        f"[bold]{brief_data['date']}[/bold]\n\n"
        f"Regime: {brief_data['regime']}\n"
        f"Sentiment: {brief_data['sentiment']:.2f}",
        title="🌅 Morning Brief"
    ))

    # Setups table
    if brief_data.get('setups'):
        table = Table(title="Top Setups")
        table.add_column("Rank", justify="center")
        table.add_column("Symbol", style="cyan")
        table.add_column("Direction", style="white")
        table.add_column("Grade", style="white")
        table.add_column("Entry", justify="right")
        table.add_column("Stop", justify="right")
        table.add_column("Target", justify="right")

        for i, setup in enumerate(brief_data['setups'], 1):
            grade_color = {'A_PLUS': 'green', 'A': 'green', 'B': 'yellow'}.get(setup['grade'], 'white')
            table.add_row(
                str(i),
                setup['symbol'],
                setup['direction'],
                f"[{grade_color}]{setup['grade']}[/{grade_color}]",
                f"{setup['entry']:.2f}",
                f"{setup['stop']:.2f}",
                f"{setup['target']:.2f}"
            )

        console.print(table)

    # Arb opportunities
    if brief_data.get('arb_opportunities'):
        console.print("\n[bold]Arbitrage Opportunities:[/bold]")
        for arb in brief_data['arb_opportunities']:
            console.print(f"  • {arb['market']}: {arb['spread_pct']:.2f}% spread")


if __name__ == "__main__":
    app()
```

### 6.2 Volume Profile Engine (`tools/volume_profile.py`)

```python
"""
Volume Profile Engine

Implements:
- Session profile calculation
- 40% Fair Value Area (FVA)
- Point of Control (POC)
- High/Low Volume Nodes (HVN/LVN)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import numpy as np
from loguru import logger


class LocationType(Enum):
    POC = "poc"
    FVA_EDGE = "fva_edge"
    HVN = "hvn"
    LVN = "lvn"
    VALUE_AREA = "value_area"
    OUTSIDE = "outside"


@dataclass
class VolumeNode:
    price: float
    volume: float
    node_type: str  # "hvn" or "lvn"


@dataclass
class VolumeProfile:
    price_levels: np.ndarray
    volumes: np.ndarray
    poc: float
    poc_volume: float
    value_area_high: float
    value_area_low: float
    fva_high: float  # 40% FVA
    fva_low: float
    hvn_levels: List[VolumeNode]
    lvn_levels: List[VolumeNode]
    total_volume: float


@dataclass
class TradeLocation:
    location_type: LocationType
    price: float
    distance_from_poc: float
    distance_from_fva: float
    nearest_hvn: Optional[float]
    nearest_lvn: Optional[float]
    score: int  # 0-25 for A+ system


def calculate_session_profile(
    bars: List[Dict],
    tick_size: float = 0.25,
    value_area_pct: float = 0.70,
    fva_pct: float = 0.40
) -> VolumeProfile:
    """
    Calculate volume profile from OHLCV bars.

    Args:
        bars: List of dicts with 'high', 'low', 'close', 'volume'
        tick_size: Price increment for bucketing
        value_area_pct: Percentage for value area (default 70%)
        fva_pct: Percentage for fair value area (default 40%)

    Returns:
        VolumeProfile with all computed values
    """
    if not bars:
        raise ValueError("No bars provided")

    # Get price range
    all_highs = [b['high'] for b in bars]
    all_lows = [b['low'] for b in bars]
    price_high = max(all_highs)
    price_low = min(all_lows)

    # Create price buckets
    num_levels = int((price_high - price_low) / tick_size) + 1
    price_levels = np.linspace(price_low, price_high, num_levels)
    volumes = np.zeros(num_levels)

    # Distribute volume across price levels
    for bar in bars:
        bar_high = bar['high']
        bar_low = bar['low']
        bar_volume = bar['volume']

        # Find touched levels
        low_idx = int((bar_low - price_low) / tick_size)
        high_idx = int((bar_high - price_low) / tick_size)

        # Distribute volume equally across touched levels
        touched_levels = high_idx - low_idx + 1
        vol_per_level = bar_volume / touched_levels

        for i in range(low_idx, min(high_idx + 1, num_levels)):
            volumes[i] += vol_per_level

    # Find POC (Point of Control)
    poc_idx = np.argmax(volumes)
    poc = price_levels[poc_idx]
    poc_volume = volumes[poc_idx]

    # Calculate Value Area (70% of volume centered on POC)
    total_volume = np.sum(volumes)
    va_high, va_low = _calculate_value_area(
        price_levels, volumes, poc_idx, total_volume, value_area_pct
    )

    # Calculate FVA (40% - tighter zone)
    fva_high, fva_low = _calculate_value_area(
        price_levels, volumes, poc_idx, total_volume, fva_pct
    )

    # Detect HVN/LVN
    hvn_levels, lvn_levels = _detect_hvn_lvn(price_levels, volumes)

    return VolumeProfile(
        price_levels=price_levels,
        volumes=volumes,
        poc=poc,
        poc_volume=poc_volume,
        value_area_high=va_high,
        value_area_low=va_low,
        fva_high=fva_high,
        fva_low=fva_low,
        hvn_levels=hvn_levels,
        lvn_levels=lvn_levels,
        total_volume=total_volume
    )


def _calculate_value_area(
    price_levels: np.ndarray,
    volumes: np.ndarray,
    poc_idx: int,
    total_volume: float,
    target_pct: float
) -> Tuple[float, float]:
    """Calculate value area bounds containing target_pct of volume."""
    target_volume = total_volume * target_pct
    accumulated = volumes[poc_idx]

    high_idx = poc_idx
    low_idx = poc_idx

    while accumulated < target_volume:
        # Look one level above and below
        can_go_high = high_idx < len(volumes) - 1
        can_go_low = low_idx > 0

        if not can_go_high and not can_go_low:
            break

        vol_above = volumes[high_idx + 1] if can_go_high else 0
        vol_below = volumes[low_idx - 1] if can_go_low else 0

        # Add the side with more volume
        if vol_above >= vol_below and can_go_high:
            high_idx += 1
            accumulated += vol_above
        elif can_go_low:
            low_idx -= 1
            accumulated += vol_below
        elif can_go_high:
            high_idx += 1
            accumulated += vol_above

    return price_levels[high_idx], price_levels[low_idx]


def _detect_hvn_lvn(
    price_levels: np.ndarray,
    volumes: np.ndarray,
    hvn_threshold: float = 1.5,  # 1.5x average = HVN
    lvn_threshold: float = 0.3   # 0.3x average = LVN
) -> Tuple[List[VolumeNode], List[VolumeNode]]:
    """Detect high and low volume nodes."""
    avg_volume = np.mean(volumes)

    hvn_levels = []
    lvn_levels = []

    # Look for local peaks (HVN) and valleys (LVN)
    for i in range(1, len(volumes) - 1):
        vol = volumes[i]
        price = price_levels[i]

        # Check if local maximum (HVN)
        if vol > volumes[i-1] and vol > volumes[i+1]:
            if vol > avg_volume * hvn_threshold:
                hvn_levels.append(VolumeNode(price, vol, "hvn"))

        # Check if local minimum (LVN)
        if vol < volumes[i-1] and vol < volumes[i+1]:
            if vol < avg_volume * lvn_threshold:
                lvn_levels.append(VolumeNode(price, vol, "lvn"))

    # Sort by volume (most significant first)
    hvn_levels.sort(key=lambda x: x.volume, reverse=True)
    lvn_levels.sort(key=lambda x: x.volume)

    return hvn_levels[:5], lvn_levels[:5]  # Top 5 each


def get_trade_location(
    current_price: float,
    profile: VolumeProfile,
    poc_tolerance: float = 2.0  # ticks
) -> TradeLocation:
    """
    Determine the trade location type for current price.

    Returns location type and score (0-25 for A+ system).
    """
    tick_size = profile.price_levels[1] - profile.price_levels[0]
    poc_distance = abs(current_price - profile.poc)
    fva_distance = min(
        abs(current_price - profile.fva_high),
        abs(current_price - profile.fva_low)
    )

    # Find nearest HVN/LVN
    nearest_hvn = None
    nearest_hvn_dist = float('inf')
    for hvn in profile.hvn_levels:
        dist = abs(current_price - hvn.price)
        if dist < nearest_hvn_dist:
            nearest_hvn = hvn.price
            nearest_hvn_dist = dist

    nearest_lvn = None
    nearest_lvn_dist = float('inf')
    for lvn in profile.lvn_levels:
        dist = abs(current_price - lvn.price)
        if dist < nearest_lvn_dist:
            nearest_lvn = lvn.price
            nearest_lvn_dist = dist

    # Determine location type and score
    if poc_distance <= poc_tolerance * tick_size:
        location_type = LocationType.POC
        score = 25  # Best location
    elif (profile.fva_low <= current_price <= profile.fva_high and
          fva_distance <= poc_tolerance * tick_size):
        location_type = LocationType.FVA_EDGE
        score = 20
    elif nearest_hvn_dist <= 3 * tick_size:
        location_type = LocationType.HVN
        score = 15
    elif nearest_lvn_dist <= 3 * tick_size:
        location_type = LocationType.LVN
        score = 18  # LVN breakouts can be good
    elif profile.value_area_low <= current_price <= profile.value_area_high:
        location_type = LocationType.VALUE_AREA
        score = 10
    else:
        location_type = LocationType.OUTSIDE
        score = 0

    return TradeLocation(
        location_type=location_type,
        price=current_price,
        distance_from_poc=poc_distance,
        distance_from_fva=fva_distance,
        nearest_hvn=nearest_hvn,
        nearest_lvn=nearest_lvn,
        score=score
    )


async def calculate_profile_for_symbol(
    symbol: str,
    timeframe: str = "1h",
    lookback_bars: int = 50,
    config=None,
    **kwargs
) -> Dict:
    """
    High-level function to calculate profile for a symbol.
    Fetches data and returns profile as dict.
    """
    from tools.market_data import fetch_ohlcv

    logger.info(f"Calculating volume profile for {symbol}")

    # Fetch OHLCV data
    ohlcv = await fetch_ohlcv(symbol, timeframe, lookback_bars)

    if not ohlcv or len(ohlcv) < 10:
        return {'error': 'Insufficient data'}

    # Calculate profile
    profile = calculate_session_profile(ohlcv)

    return {
        'symbol': symbol,
        'poc': profile.poc,
        'fva_high': profile.fva_high,
        'fva_low': profile.fva_low,
        'value_area_high': profile.value_area_high,
        'value_area_low': profile.value_area_low,
        'hvn_levels': [{'price': h.price, 'volume': h.volume} for h in profile.hvn_levels],
        'lvn_levels': [{'price': l.price, 'volume': l.volume} for l in profile.lvn_levels],
        'total_volume': profile.total_volume
    }
```

### 6.3 Order Flow Engine (`tools/order_flow.py`)

```python
"""
Order Flow Engine

Implements:
- CVD (Cumulative Volume Delta) tracking
- Extreme delta detection
- Divergence detection
- Exhaustion detection
- Volume analysis
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from enum import Enum
import numpy as np
from loguru import logger


class CVDState(Enum):
    CONFIRMING = "confirming"
    DIVERGING = "diverging"
    EXHAUSTING = "exhausting"
    NEUTRAL = "neutral"


class VolumeState(Enum):
    NORMAL = "normal"
    EXPANSION = "expansion"
    CLIMAX = "climax"
    CONTRACTION = "contraction"


@dataclass
class CVDData:
    values: np.ndarray
    current: float
    session_high: float
    session_low: float
    is_extreme: bool
    state: CVDState


@dataclass
class OrderFlowSignals:
    cvd: CVDData
    volume_state: VolumeState
    delta_extreme: bool
    divergence_detected: bool
    exhaustion_detected: bool
    footprint_signal: str  # "absorption", "failed_imbalance", "one_sided", "none"
    flow_score: int  # 0-25 for A+ system


def calculate_cvd(
    ticks: List[Dict],
    reset_on_session: bool = True
) -> CVDData:
    """
    Calculate Cumulative Volume Delta from tick data.

    Args:
        ticks: List of {'price': float, 'volume': int, 'side': 'buy'|'sell'}
        reset_on_session: Reset CVD at session start

    Returns:
        CVDData with running CVD values and state
    """
    if not ticks:
        return CVDData(
            values=np.array([0]),
            current=0,
            session_high=0,
            session_low=0,
            is_extreme=False,
            state=CVDState.NEUTRAL
        )

    cvd_values = []
    running_cvd = 0

    for tick in ticks:
        volume = tick['volume']
        side = tick.get('side', 'unknown')

        if side == 'buy':
            running_cvd += volume
        elif side == 'sell':
            running_cvd -= volume
        # If side unknown, use price movement heuristic

        cvd_values.append(running_cvd)

    cvd_array = np.array(cvd_values)
    session_high = np.max(cvd_array)
    session_low = np.min(cvd_array)
    current = cvd_array[-1]

    # Determine if extreme (within 10% of session high/low)
    range_size = session_high - session_low
    if range_size > 0:
        high_threshold = session_high - (range_size * 0.1)
        low_threshold = session_low + (range_size * 0.1)
        is_extreme = current >= high_threshold or current <= low_threshold
    else:
        is_extreme = False

    # Determine state (simplified - would need price data for full analysis)
    state = CVDState.NEUTRAL
    if is_extreme:
        state = CVDState.CONFIRMING  # At extreme, likely confirming trend

    return CVDData(
        values=cvd_array,
        current=current,
        session_high=session_high,
        session_low=session_low,
        is_extreme=is_extreme,
        state=state
    )


def detect_divergence(
    prices: List[float],
    cvd: CVDData,
    lookback: int = 20
) -> bool:
    """
    Detect price/CVD divergence.

    Bearish divergence: Price makes higher high, CVD makes lower high
    Bullish divergence: Price makes lower low, CVD makes higher low
    """
    if len(prices) < lookback or len(cvd.values) < lookback:
        return False

    recent_prices = prices[-lookback:]
    recent_cvd = cvd.values[-lookback:]

    # Find recent highs/lows
    price_high_idx = np.argmax(recent_prices)
    price_low_idx = np.argmin(recent_prices)
    cvd_high_idx = np.argmax(recent_cvd)
    cvd_low_idx = np.argmin(recent_cvd)

    # Check for bearish divergence (price high after CVD high)
    if price_high_idx > cvd_high_idx:
        if recent_prices[price_high_idx] > recent_prices[cvd_high_idx]:
            if recent_cvd[price_high_idx] < recent_cvd[cvd_high_idx]:
                return True  # Bearish divergence

    # Check for bullish divergence (price low after CVD low)
    if price_low_idx > cvd_low_idx:
        if recent_prices[price_low_idx] < recent_prices[cvd_low_idx]:
            if recent_cvd[price_low_idx] > recent_cvd[cvd_low_idx]:
                return True  # Bullish divergence

    return False


def detect_exhaustion(
    cvd: CVDData,
    prices: List[float],
    volume: List[float],
    lookback: int = 10
) -> bool:
    """
    Detect exhaustion: CVD flattens while price continues trending.
    """
    if len(prices) < lookback or len(cvd.values) < lookback:
        return False

    recent_cvd = cvd.values[-lookback:]
    recent_prices = prices[-lookback:]

    # Calculate CVD slope (should be flattening)
    cvd_slope = (recent_cvd[-1] - recent_cvd[0]) / lookback

    # Calculate price slope (should be continuing)
    price_slope = (recent_prices[-1] - recent_prices[0]) / lookback

    # Exhaustion: price moving but CVD flattening
    cvd_range = np.max(recent_cvd) - np.min(recent_cvd)
    price_range = np.max(recent_prices) - np.min(recent_prices)

    if price_range > 0:
        # CVD should be relatively flat compared to price movement
        cvd_normalized = abs(cvd_slope) / (cvd_range + 1)
        price_normalized = abs(price_slope) / price_range

        if price_normalized > 0.5 and cvd_normalized < 0.2:
            return True

    return False


def analyze_volume(
    volumes: List[float],
    lookback: int = 20,
    expansion_threshold: float = 1.5,
    climax_threshold: float = 3.0
) -> VolumeState:
    """
    Analyze volume relative to session average.
    """
    if not volumes or len(volumes) < lookback:
        return VolumeState.NORMAL

    recent = volumes[-lookback:]
    avg_volume = np.mean(recent[:-1])  # Average excluding current
    current_volume = recent[-1]

    if avg_volume == 0:
        return VolumeState.NORMAL

    ratio = current_volume / avg_volume

    if ratio >= climax_threshold:
        return VolumeState.CLIMAX
    elif ratio >= expansion_threshold:
        return VolumeState.EXPANSION
    elif ratio <= 0.5:
        return VolumeState.CONTRACTION
    else:
        return VolumeState.NORMAL


def detect_absorption(
    bid_volume: float,
    ask_volume: float,
    price_change: float,
    threshold: float = 2.0
) -> bool:
    """
    Detect absorption: Large volume on one side but price doesn't move.
    """
    total_volume = bid_volume + ask_volume
    if total_volume == 0:
        return False

    imbalance = abs(bid_volume - ask_volume) / total_volume

    # High imbalance but small price change = absorption
    if imbalance > 0.6 and abs(price_change) < 0.1:  # Adjust thresholds as needed
        return True

    return False


def get_order_flow_signals(
    ticks: List[Dict] = None,
    prices: List[float] = None,
    volumes: List[float] = None,
    **kwargs
) -> OrderFlowSignals:
    """
    Get comprehensive order flow analysis.

    Returns:
        OrderFlowSignals with all signals and A+ flow score (0-25)
    """
    # Calculate CVD
    cvd = calculate_cvd(ticks or [])

    # Analyze volume
    volume_state = analyze_volume(volumes or [])

    # Detect signals
    divergence = detect_divergence(prices or [], cvd) if prices else False
    exhaustion = detect_exhaustion(cvd, prices or [], volumes or []) if prices else False

    # Determine CVD state
    if divergence:
        cvd.state = CVDState.DIVERGING
    elif exhaustion:
        cvd.state = CVDState.EXHAUSTING
    elif cvd.is_extreme:
        cvd.state = CVDState.CONFIRMING

    # Calculate flow score (0-25)
    score = 0

    # CVD confirmation (0-15 points)
    if cvd.state == CVDState.CONFIRMING:
        score += 15
    elif cvd.state == CVDState.DIVERGING:
        score += 10  # Divergence is good for reversal trades
    elif cvd.state == CVDState.EXHAUSTING:
        score += 8

    # Volume expansion (0-5 points)
    if volume_state == VolumeState.EXPANSION:
        score += 5
    elif volume_state == VolumeState.CLIMAX:
        score += 3  # Climax can signal reversal

    # Footprint signals (0-5 points)
    footprint_signal = "none"
    # Would need real footprint data for this

    return OrderFlowSignals(
        cvd=cvd,
        volume_state=volume_state,
        delta_extreme=cvd.is_extreme,
        divergence_detected=divergence,
        exhaustion_detected=exhaustion,
        footprint_signal=footprint_signal,
        flow_score=min(score, 25)
    )
```

### 6.4 A+ Scoring Engine (`tools/scoring.py`)

```python
"""
A+ Scoring Engine

Deterministic scoring system for trade setups:
- Location Score (0-25)
- Order Flow Score (0-25)
- Setup Quality Score (0-25)
- Regime Alignment Score (0-25)

Total: 0-100
Grades: A+ (85+), A (75-84), B (60-74), C (<60 = NO TRADE)
"""

from dataclasses import dataclass
from typing import Dict, Optional, List
from enum import Enum
from datetime import datetime
from loguru import logger


class TradeGrade(Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"
    NO_TRADE = "NO_TRADE"


class SetupType(Enum):
    POC_BOUNCE = "poc_bounce"
    FVA_EDGE_FADE = "fva_edge_fade"
    LVN_BREAKOUT = "lvn_breakout"
    NONE = "none"


@dataclass
class ScoreBreakdown:
    location_pts: int
    flow_pts: int
    setup_pts: int
    regime_pts: int
    total: int
    grade: TradeGrade
    setup_type: SetupType
    size_modifier: float  # 1.0 for A+/A, 0.5 for B, 0 for C
    trade_allowed: bool
    notes: List[str]


async def score_setup(
    symbol: str,
    current_price: float = None,
    config=None,
    **kwargs
) -> ScoreBreakdown:
    """
    Score a trading setup using the A+ system.

    Fetches all required data and returns comprehensive score.
    """
    from tools.volume_profile import calculate_profile_for_symbol, get_trade_location
    from tools.order_flow import get_order_flow_signals
    from tools.analysis import calculate_technicals
    from tools.market_data import fetch_current_price, fetch_ohlcv

    logger.info(f"Scoring setup for {symbol}")
    notes = []

    # Get current price if not provided
    if current_price is None:
        price_data = await fetch_current_price(symbol)
        current_price = price_data.get('price', 0)

    # 1. LOCATION SCORE (0-25)
    profile_data = await calculate_profile_for_symbol(symbol)
    if 'error' in profile_data:
        location_pts = 0
        notes.append("Could not calculate volume profile")
    else:
        from tools.volume_profile import VolumeProfile, VolumeNode, get_trade_location

        # Reconstruct profile object for location analysis
        profile = VolumeProfile(
            price_levels=None,  # Not needed for location check
            volumes=None,
            poc=profile_data['poc'],
            poc_volume=0,
            value_area_high=profile_data['value_area_high'],
            value_area_low=profile_data['value_area_low'],
            fva_high=profile_data['fva_high'],
            fva_low=profile_data['fva_low'],
            hvn_levels=[VolumeNode(h['price'], h['volume'], 'hvn') for h in profile_data['hvn_levels']],
            lvn_levels=[VolumeNode(l['price'], l['volume'], 'lvn') for l in profile_data['lvn_levels']],
            total_volume=profile_data['total_volume']
        )

        location = get_trade_location(current_price, profile)
        location_pts = location.score
        notes.append(f"Location: {location.location_type.value} ({location_pts}pts)")

    # 2. ORDER FLOW SCORE (0-25)
    flow_signals = get_order_flow_signals()  # Would need real tick data
    flow_pts = flow_signals.flow_score
    notes.append(f"Order flow: {flow_signals.cvd.state.value} ({flow_pts}pts)")

    # 3. SETUP QUALITY SCORE (0-25)
    setup_type, setup_pts = _classify_setup(
        location_pts, flow_signals, profile_data if 'error' not in profile_data else None
    )
    notes.append(f"Setup: {setup_type.value} ({setup_pts}pts)")

    # 4. REGIME ALIGNMENT SCORE (0-25)
    ohlcv = await fetch_ohlcv(symbol, "1h", 50)
    if ohlcv:
        technicals = calculate_technicals(ohlcv)
        regime_pts = _score_regime(technicals)
        notes.append(f"Regime: {technicals.get('trend', 'neutral')} ({regime_pts}pts)")
    else:
        regime_pts = 10  # Neutral default
        notes.append("Could not determine regime")

    # Calculate total and grade
    total = location_pts + flow_pts + setup_pts + regime_pts
    grade = _calculate_grade(total)

    # Size modifier
    size_modifiers = {
        TradeGrade.A_PLUS: 1.0,
        TradeGrade.A: 1.0,
        TradeGrade.B: 0.5,
        TradeGrade.NO_TRADE: 0.0
    }

    return ScoreBreakdown(
        location_pts=location_pts,
        flow_pts=flow_pts,
        setup_pts=setup_pts,
        regime_pts=regime_pts,
        total=total,
        grade=grade,
        setup_type=setup_type,
        size_modifier=size_modifiers[grade],
        trade_allowed=grade != TradeGrade.NO_TRADE,
        notes=notes
    )


def _classify_setup(
    location_pts: int,
    flow_signals,
    profile_data: Optional[Dict]
) -> tuple:
    """Classify the setup type and score quality."""

    # Determine setup type based on location
    if location_pts >= 23:  # At POC
        setup_type = SetupType.POC_BOUNCE
        base_score = 20
    elif location_pts >= 18:  # At FVA edge
        setup_type = SetupType.FVA_EDGE_FADE
        base_score = 18
    elif location_pts >= 15:  # At LVN
        setup_type = SetupType.LVN_BREAKOUT
        base_score = 15
    else:
        setup_type = SetupType.NONE
        base_score = 0

    # Adjust for flow confirmation
    if flow_signals.cvd.state.value == "confirming":
        base_score += 5
    elif flow_signals.divergence_detected:
        base_score += 3

    return setup_type, min(base_score, 25)


def _score_regime(technicals: Dict) -> int:
    """Score regime alignment (0-25)."""
    score = 10  # Start neutral

    trend = technicals.get('trend', 'neutral')
    if trend == 'bullish':
        score += 8
    elif trend == 'bearish':
        score += 8
    # Neutral trend is okay but not ideal

    # RSI not extreme
    rsi = technicals.get('indicators', {}).get('rsi_14', 50)
    if 30 <= rsi <= 70:
        score += 5
    elif rsi < 30 or rsi > 70:
        score += 2  # Extreme can work for reversals

    return min(score, 25)


def _calculate_grade(total: int) -> TradeGrade:
    """Convert total score to grade."""
    if total >= 85:
        return TradeGrade.A_PLUS
    elif total >= 75:
        return TradeGrade.A
    elif total >= 60:
        return TradeGrade.B
    else:
        return TradeGrade.NO_TRADE


def create_trade_object(
    symbol: str,
    direction: str,
    score: ScoreBreakdown,
    profile_data: Dict,
    entry_price: float,
    config=None
) -> Dict:
    """
    Create standardized trade object from scored setup.
    """
    # Calculate stops and targets based on profile
    poc = profile_data.get('poc', entry_price)
    fva_high = profile_data.get('fva_high', entry_price * 1.01)
    fva_low = profile_data.get('fva_low', entry_price * 0.99)

    if direction == 'long':
        stop = fva_low - (fva_high - fva_low) * 0.1  # Below FVA
        target1 = poc
        target2 = fva_high
    else:
        stop = fva_high + (fva_high - fva_low) * 0.1  # Above FVA
        target1 = poc
        target2 = fva_low

    risk_per_share = abs(entry_price - stop)

    return {
        'id': f"trade_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        'symbol': symbol,
        'direction': direction,
        'strategy_template_id': score.setup_type.value,

        'location': {
            'type': score.setup_type.value,
            'price_level': entry_price,
            'distance_from_poc': abs(entry_price - poc)
        },

        'score': {
            'location_pts': score.location_pts,
            'flow_pts': score.flow_pts,
            'setup_pts': score.setup_pts,
            'regime_pts': score.regime_pts,
            'total': score.total,
            'grade': score.grade.value
        },

        'entry': {
            'trigger': f"Limit at {entry_price}",
            'price': entry_price,
            'order_type': 'limit'
        },

        'stop': {
            'price': stop,
            'type': 'structural',
            'reason': 'Below FVA' if direction == 'long' else 'Above FVA'
        },

        'targets': {
            't1': {'price': target1, 'size_pct': 50, 'reason': 'POC'},
            't2': {'price': target2, 'size_pct': 50, 'reason': 'FVA edge'}
        },

        'risk': {
            'risk_per_share': risk_per_share,
            'size_modifier': score.size_modifier
        },

        'execution': {
            'mode': 'SIGNAL_ONLY',  # Default, router will determine
            'venue': 'auto',
            'state': 'SCORED'
        },

        'created_at': datetime.utcnow().isoformat()
    }
```

### 6.5 Arbitrage Scanner (`tools/arbitrage.py`)

```python
"""
Arbitrage Scanner

Scans for prediction market arbitrage opportunities:
- Type A: Sum arbitrage (single platform)
- Type B: Cross-platform arbitrage
- Type C: Multi-outcome arbitrage
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime
from loguru import logger
import asyncio


@dataclass
class ArbOpportunity:
    type: str  # "sum", "cross_platform", "multi_outcome"
    market: str
    platforms: str
    spread_pct: float
    yes_price: float
    no_price: float
    liquidity: float
    expected_profit: float
    confidence: float
    valid: bool
    reason: str


async def scan_arbitrage(
    min_spread_pct: float = 1.0,
    max_results: int = 10,
    config=None,
    **kwargs
) -> List[ArbOpportunity]:
    """
    Scan all platforms for arbitrage opportunities.
    """
    logger.info(f"Scanning for arbitrage opportunities (min spread: {min_spread_pct}%)")

    opportunities = []

    # Scan each type
    sum_arbs = await _scan_sum_arbitrage(min_spread_pct)
    cross_arbs = await _scan_cross_platform_arbitrage(min_spread_pct)
    multi_arbs = await _scan_multi_outcome_arbitrage(min_spread_pct)

    opportunities.extend(sum_arbs)
    opportunities.extend(cross_arbs)
    opportunities.extend(multi_arbs)

    # Sort by spread (best first)
    opportunities.sort(key=lambda x: x.spread_pct, reverse=True)

    return opportunities[:max_results]


async def _scan_sum_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type A: Sum arbitrage on single platform.

    Condition: YES_price + NO_price < $1.00 (minus fees)
    """
    opportunities = []

    # Scan Polymarket
    try:
        from tools.market_data import fetch_polymarket
        poly_data = await fetch_polymarket()

        for market in poly_data.get('markets', []):
            if not isinstance(market, dict):
                continue

            # Get YES/NO prices
            yes_price = market.get('yes_price', market.get('outcomePrices', [0.5])[0])
            no_price = market.get('no_price', 1 - yes_price if yes_price else 0.5)

            # Check for sum arb
            total = yes_price + no_price
            if total < 0.995:  # Account for ~0.5% fees
                spread_pct = (1.0 - total) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="sum",
                        market=market.get('question', market.get('title', 'Unknown'))[:50],
                        platforms="Polymarket",
                        spread_pct=spread_pct,
                        yes_price=yes_price,
                        no_price=no_price,
                        liquidity=market.get('liquidity', 0),
                        expected_profit=spread_pct / 100,
                        confidence=0.9,
                        valid=True,
                        reason="Sum < 1.00"
                    ))
    except Exception as e:
        logger.error(f"Polymarket scan failed: {e}")

    # Scan Kalshi
    try:
        from tools.kalshi import fetch_kalshi_markets
        kalshi_data = await fetch_kalshi_markets()

        for market in kalshi_data.get('markets', []):
            yes_price = market.get('yes_price', 0.5)
            no_price = market.get('no_price', 0.5)

            total = yes_price + no_price
            if total < 0.995:
                spread_pct = (1.0 - total) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="sum",
                        market=market.get('title', 'Unknown')[:50],
                        platforms="Kalshi",
                        spread_pct=spread_pct,
                        yes_price=yes_price,
                        no_price=no_price,
                        liquidity=market.get('volume', 0),
                        expected_profit=spread_pct / 100,
                        confidence=0.95,  # Kalshi is regulated
                        valid=True,
                        reason="Sum < 1.00"
                    ))
    except Exception as e:
        logger.error(f"Kalshi scan failed: {e}")

    return opportunities


async def _scan_cross_platform_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type B: Cross-platform arbitrage.

    Condition: Platform1_YES + Platform2_NO < $1.00
    """
    opportunities = []

    # Need to match markets across platforms
    # This is complex - requires fuzzy matching of event descriptions

    try:
        from tools.market_data import fetch_polymarket
        from tools.kalshi import fetch_kalshi_markets

        poly_markets = await fetch_polymarket()
        kalshi_markets = await fetch_kalshi_markets()

        # Match markets by similar questions
        matched = _match_markets(
            poly_markets.get('markets', []),
            kalshi_markets.get('markets', [])
        )

        for match in matched:
            poly_yes = match['polymarket']['yes_price']
            kalshi_no = match['kalshi']['no_price']

            # Check Poly YES + Kalshi NO
            if poly_yes + kalshi_no < 0.985:  # Higher threshold for cross-platform
                spread_pct = (1.0 - poly_yes - kalshi_no) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="cross_platform",
                        market=match['question'][:50],
                        platforms="Polymarket + Kalshi",
                        spread_pct=spread_pct,
                        yes_price=poly_yes,
                        no_price=kalshi_no,
                        liquidity=min(
                            match['polymarket'].get('liquidity', 0),
                            match['kalshi'].get('volume', 0)
                        ),
                        expected_profit=spread_pct / 100,
                        confidence=0.8,  # Lower due to resolution risk
                        valid=True,
                        reason="Cross-platform spread"
                    ))

            # Also check Kalshi YES + Poly NO
            kalshi_yes = match['kalshi']['yes_price']
            poly_no = match['polymarket']['no_price']

            if kalshi_yes + poly_no < 0.985:
                spread_pct = (1.0 - kalshi_yes - poly_no) * 100

                if spread_pct >= min_spread_pct:
                    opportunities.append(ArbOpportunity(
                        type="cross_platform",
                        market=match['question'][:50],
                        platforms="Kalshi + Polymarket",
                        spread_pct=spread_pct,
                        yes_price=kalshi_yes,
                        no_price=poly_no,
                        liquidity=min(
                            match['polymarket'].get('liquidity', 0),
                            match['kalshi'].get('volume', 0)
                        ),
                        expected_profit=spread_pct / 100,
                        confidence=0.8,
                        valid=True,
                        reason="Cross-platform spread"
                    ))

    except Exception as e:
        logger.error(f"Cross-platform scan failed: {e}")

    return opportunities


async def _scan_multi_outcome_arbitrage(min_spread_pct: float) -> List[ArbOpportunity]:
    """
    Type C: Multi-outcome arbitrage.

    Condition: Sum of all outcomes < $1.00
    """
    opportunities = []

    # For multi-outcome markets (e.g., "Who wins election?")
    # Sum all outcome prices - if < 1.00, buy all proportionally

    # Implementation depends on specific market structure
    # Placeholder for now

    return opportunities


def _match_markets(
    poly_markets: List[Dict],
    kalshi_markets: List[Dict]
) -> List[Dict]:
    """
    Match markets across platforms using fuzzy string matching.
    """
    matched = []

    # Simple keyword matching (would use better NLP in production)
    for poly in poly_markets:
        poly_q = str(poly.get('question', poly.get('title', ''))).lower()

        for kalshi in kalshi_markets:
            kalshi_q = str(kalshi.get('title', '')).lower()

            # Check for common keywords
            poly_words = set(poly_q.split())
            kalshi_words = set(kalshi_q.split())

            overlap = poly_words & kalshi_words
            # Filter out common words
            overlap -= {'will', 'the', 'be', 'in', 'on', 'by', 'a', 'an', 'to', 'of'}

            if len(overlap) >= 3:  # At least 3 meaningful words match
                matched.append({
                    'question': poly_q[:50],
                    'polymarket': {
                        'yes_price': poly.get('yes_price', 0.5),
                        'no_price': poly.get('no_price', 0.5),
                        'liquidity': poly.get('liquidity', 0)
                    },
                    'kalshi': {
                        'yes_price': kalshi.get('yes_price', 0.5),
                        'no_price': kalshi.get('no_price', 0.5),
                        'volume': kalshi.get('volume', 0)
                    }
                })

    return matched


async def execute_arbitrage(
    opportunity: ArbOpportunity,
    size: float,
    config=None
) -> Dict:
    """
    Execute an arbitrage trade.

    Places simultaneous orders on both sides.
    """
    logger.info(f"Executing {opportunity.type} arb: {opportunity.market}")

    results = {
        'opportunity': opportunity,
        'size': size,
        'orders': [],
        'status': 'pending',
        'executed_at': datetime.utcnow().isoformat()
    }

    # Execute based on type
    if opportunity.type == "sum":
        # Buy both YES and NO on same platform
        platform = opportunity.platforms.lower()

        if 'polymarket' in platform:
            from tools.polymarket import place_order as poly_order

            yes_order = await poly_order(
                market=opportunity.market,
                side='yes',
                size=size,
                price=opportunity.yes_price
            )
            no_order = await poly_order(
                market=opportunity.market,
                side='no',
                size=size,
                price=opportunity.no_price
            )

            results['orders'] = [yes_order, no_order]

    elif opportunity.type == "cross_platform":
        # Buy on different platforms simultaneously
        from tools.polymarket import place_order as poly_order
        from tools.kalshi import place_order as kalshi_order

        # Execute both in parallel
        orders = await asyncio.gather(
            poly_order(
                market=opportunity.market,
                side='yes',
                size=size,
                price=opportunity.yes_price
            ),
            kalshi_order(
                market=opportunity.market,
                side='no',
                size=size,
                price=opportunity.no_price
            ),
            return_exceptions=True
        )

        results['orders'] = orders

    # Check if both filled
    all_filled = all(
        o.get('status') == 'filled'
        for o in results['orders']
        if isinstance(o, dict)
    )

    results['status'] = 'filled' if all_filled else 'partial'

    return results
```

### 6.6 OANDA Adapter (`tools/oanda.py`)

```python
"""
OANDA v20 API Adapter

For XAUUSD (gold) trading - AUTO execution mode.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

try:
    import oandapyV20
    from oandapyV20 import API
    from oandapyV20.endpoints import accounts, orders, positions, pricing, instruments
    OANDA_AVAILABLE = True
except ImportError:
    OANDA_AVAILABLE = False
    logger.warning("oandapyV20 not installed")


class OANDAClient:
    """OANDA v20 API client."""

    def __init__(self):
        self.api_key = os.getenv('OANDA_API_KEY')
        self.account_id = os.getenv('OANDA_ACCOUNT_ID')
        self.environment = os.getenv('OANDA_ENVIRONMENT', 'practice')  # 'practice' or 'live'

        if not OANDA_AVAILABLE:
            self.client = None
            return

        if self.api_key and self.account_id:
            self.client = API(
                access_token=self.api_key,
                environment=self.environment
            )
        else:
            self.client = None
            logger.warning("OANDA credentials not configured")

    async def get_account(self) -> Dict:
        """Get account details."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            r = accounts.AccountDetails(self.account_id)
            response = self.client.request(r)
            return response.get('account', {})
        except Exception as e:
            logger.error(f"OANDA account error: {e}")
            return {'error': str(e)}

    async def get_positions(self) -> List[Dict]:
        """Get open positions."""
        if not self.client:
            return []

        try:
            r = positions.OpenPositions(self.account_id)
            response = self.client.request(r)

            result = []
            for pos in response.get('positions', []):
                long_units = float(pos.get('long', {}).get('units', 0))
                short_units = float(pos.get('short', {}).get('units', 0))

                if long_units != 0:
                    result.append({
                        'venue': 'OANDA',
                        'symbol': pos['instrument'],
                        'side': 'long',
                        'size': long_units,
                        'entry': float(pos['long'].get('averagePrice', 0)),
                        'current': 0,  # Would need to fetch current price
                        'pnl': float(pos['long'].get('unrealizedPL', 0))
                    })

                if short_units != 0:
                    result.append({
                        'venue': 'OANDA',
                        'symbol': pos['instrument'],
                        'side': 'short',
                        'size': abs(short_units),
                        'entry': float(pos['short'].get('averagePrice', 0)),
                        'current': 0,
                        'pnl': float(pos['short'].get('unrealizedPL', 0))
                    })

            return result
        except Exception as e:
            logger.error(f"OANDA positions error: {e}")
            return []

    async def get_price(self, instrument: str = "XAU_USD") -> Dict:
        """Get current price."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            params = {"instruments": instrument}
            r = pricing.PricingInfo(self.account_id, params=params)
            response = self.client.request(r)

            prices = response.get('prices', [])
            if prices:
                return {
                    'instrument': instrument,
                    'bid': float(prices[0]['bids'][0]['price']),
                    'ask': float(prices[0]['asks'][0]['price']),
                    'time': prices[0]['time']
                }
            return {'error': 'No price data'}
        except Exception as e:
            logger.error(f"OANDA price error: {e}")
            return {'error': str(e)}

    async def place_order(
        self,
        instrument: str,
        units: int,
        side: str,
        order_type: str = "MARKET",
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None
    ) -> Dict:
        """
        Place an order.

        Args:
            instrument: e.g., "XAU_USD"
            units: Number of units (positive for buy, use side param)
            side: "buy" or "sell"
            order_type: "MARKET" or "LIMIT"
            price: Limit price (for LIMIT orders)
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        if not self.client:
            return {'error': 'Not connected', 'status': 'failed'}

        # Adjust units for direction
        if side == "sell":
            units = -abs(units)
        else:
            units = abs(units)

        logger.info(f"OANDA: Placing {side} order for {units} {instrument}")

        try:
            order_data = {
                "order": {
                    "instrument": instrument,
                    "units": str(units),
                    "type": order_type,
                    "positionFill": "DEFAULT"
                }
            }

            if order_type == "LIMIT" and price:
                order_data["order"]["price"] = str(price)

            if stop_loss:
                order_data["order"]["stopLossOnFill"] = {
                    "price": str(stop_loss)
                }

            if take_profit:
                order_data["order"]["takeProfitOnFill"] = {
                    "price": str(take_profit)
                }

            r = orders.OrderCreate(self.account_id, data=order_data)
            response = self.client.request(r)

            return {
                'status': 'filled' if 'orderFillTransaction' in response else 'pending',
                'order_id': response.get('orderFillTransaction', {}).get('id'),
                'fill_price': response.get('orderFillTransaction', {}).get('price'),
                'units': units,
                'instrument': instrument,
                'venue': 'OANDA',
                'executed_at': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"OANDA order error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def close_position(self, instrument: str = "XAU_USD") -> Dict:
        """Close all positions for an instrument."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            data = {"longUnits": "ALL", "shortUnits": "ALL"}
            r = positions.PositionClose(self.account_id, instrument, data)
            response = self.client.request(r)

            return {
                'status': 'closed',
                'instrument': instrument,
                'response': response
            }
        except Exception as e:
            logger.error(f"OANDA close error: {e}")
            return {'error': str(e)}


# Singleton instance
_oanda_client = None


def get_oanda_client() -> OANDAClient:
    global _oanda_client
    if _oanda_client is None:
        _oanda_client = OANDAClient()
    return _oanda_client


# Convenience functions
async def oanda_get_price(instrument: str = "XAU_USD") -> Dict:
    return await get_oanda_client().get_price(instrument)


async def oanda_place_order(**kwargs) -> Dict:
    return await get_oanda_client().place_order(**kwargs)


async def oanda_get_positions() -> List[Dict]:
    return await get_oanda_client().get_positions()


async def oanda_close_position(instrument: str = "XAU_USD") -> Dict:
    return await get_oanda_client().close_position(instrument)
```

### 6.7 Kalshi Adapter (`tools/kalshi.py`)

```python
"""
Kalshi API Adapter

For regulated prediction market trading - AUTO execution mode.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
import aiohttp


class KalshiClient:
    """Kalshi API client."""

    BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"

    def __init__(self):
        self.email = os.getenv('KALSHI_EMAIL')
        self.password = os.getenv('KALSHI_PASSWORD')
        self.token = None

    async def _ensure_authenticated(self):
        """Ensure we have a valid auth token."""
        if self.token:
            return True

        if not self.email or not self.password:
            logger.warning("Kalshi credentials not configured")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.BASE_URL}/login",
                    json={"email": self.email, "password": self.password}
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.token = data.get('token')
                        return True
                    else:
                        logger.error(f"Kalshi login failed: {resp.status}")
                        return False
        except Exception as e:
            logger.error(f"Kalshi auth error: {e}")
            return False

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Content-Type": "application/json"
        }

    async def get_markets(self, status: str = "open") -> List[Dict]:
        """Get available markets."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/markets",
                    params={"status": status},
                    headers=self._headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get('markets', [])
                    return []
        except Exception as e:
            logger.error(f"Kalshi markets error: {e}")
            return []

    async def get_positions(self) -> List[Dict]:
        """Get current positions."""
        if not await self._ensure_authenticated():
            return []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/portfolio/positions",
                    headers=self._headers()
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        positions = []
                        for pos in data.get('market_positions', []):
                            positions.append({
                                'venue': 'Kalshi',
                                'symbol': pos.get('ticker', ''),
                                'side': 'yes' if pos.get('position', 0) > 0 else 'no',
                                'size': abs(pos.get('position', 0)),
                                'entry': pos.get('average_price', 0),
                                'current': pos.get('market_price', 0),
                                'pnl': pos.get('unrealized_pnl', 0)
                            })
                        return positions
                    return []
        except Exception as e:
            logger.error(f"Kalshi positions error: {e}")
            return []

    async def place_order(
        self,
        ticker: str,
        side: str,  # "yes" or "no"
        size: int,
        price: float,  # 0.01 to 0.99
        order_type: str = "limit"
    ) -> Dict:
        """Place an order on Kalshi."""
        if not await self._ensure_authenticated():
            return {'error': 'Not authenticated', 'status': 'failed'}

        logger.info(f"Kalshi: Placing {side} order for {size} contracts on {ticker} @ {price}")

        try:
            order_data = {
                "ticker": ticker,
                "action": "buy",  # Always buy, side determines yes/no
                "side": side,
                "count": size,
                "type": order_type
            }

            if order_type == "limit":
                order_data["yes_price"] = int(price * 100) if side == "yes" else None
                order_data["no_price"] = int(price * 100) if side == "no" else None

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.BASE_URL}/portfolio/orders",
                    json=order_data,
                    headers=self._headers()
                ) as resp:
                    if resp.status in [200, 201]:
                        data = await resp.json()
                        return {
                            'status': 'filled' if data.get('order', {}).get('status') == 'executed' else 'pending',
                            'order_id': data.get('order', {}).get('order_id'),
                            'ticker': ticker,
                            'side': side,
                            'size': size,
                            'price': price,
                            'venue': 'Kalshi',
                            'executed_at': datetime.utcnow().isoformat()
                        }
                    else:
                        error = await resp.text()
                        return {'error': error, 'status': 'failed'}

        except Exception as e:
            logger.error(f"Kalshi order error: {e}")
            return {'error': str(e), 'status': 'failed'}


# Singleton
_kalshi_client = None


def get_kalshi_client() -> KalshiClient:
    global _kalshi_client
    if _kalshi_client is None:
        _kalshi_client = KalshiClient()
    return _kalshi_client


async def fetch_kalshi_markets() -> Dict:
    """Fetch Kalshi markets."""
    markets = await get_kalshi_client().get_markets()

    # Normalize to common format
    normalized = []
    for m in markets:
        normalized.append({
            'title': m.get('title', ''),
            'ticker': m.get('ticker', ''),
            'yes_price': m.get('yes_price', 50) / 100,  # Convert cents to dollars
            'no_price': m.get('no_price', 50) / 100,
            'volume': m.get('volume', 0)
        })

    return {'markets': normalized}


async def place_order(**kwargs) -> Dict:
    return await get_kalshi_client().place_order(**kwargs)


async def kalshi_get_positions() -> List[Dict]:
    return await get_kalshi_client().get_positions()
```

---

## 7. Execution Matrix

| Instrument | Venue | Mode | When Available |
|------------|-------|------|----------------|
| **XAUUSD (Gold)** | OANDA | **AUTO** | Now |
| **Kalshi Events** | Kalshi | **AUTO** | Now |
| **Polymarket** | Polymarket | **AUTO** | Now |
| **NQ/ES/GC Futures** | NinjaTrader/Rithmic | **SIGNAL_ONLY** | Signal only (no auto) |
| **SPY/QQQ Options** | Schwab | **SIGNAL_ONLY** | Pending approval |

---

## 8. Build Order

### Phase 1: Foundation (Day 1-2)
```
1. Install new dependencies (requirements.txt)
2. Create cli.py with Typer
3. Create dexter/ package structure
4. Test: dexter --help works
```

### Phase 2: Analytics (Day 3-4)
```
1. Implement volume_profile.py
2. Implement order_flow.py
3. Implement scoring.py
4. Test: dexter score SPY works
```

### Phase 3: Execution (Day 5-6)
```
1. Implement oanda.py
2. Implement kalshi.py
3. Update polymarket.py
4. Test: dexter positions works
```

### Phase 4: Arbitrage (Day 7)
```
1. Implement arbitrage.py
2. Test: dexter arb works
3. Test: dexter arb --execute (small size)
```

### Phase 5: Integration (Day 8)
```
1. Wire everything into scheduler
2. Create morning brief generator
3. Test full cycle: research → score → report → execute
```

---

## Environment Variables Needed

```bash
# .env file
OPENAI_API_KEY=sk-xxx
OANDA_API_KEY=xxx
OANDA_ACCOUNT_ID=xxx
OANDA_ENVIRONMENT=practice  # or 'live'
KALSHI_EMAIL=xxx
KALSHI_PASSWORD=xxx
POLYGON_API_KEY=xxx
SENDGRID_API_KEY=xxx
TWILIO_ACCOUNT_SID=xxx
TWILIO_AUTH_TOKEN=xxx
```

---

## Quick Start Commands

```bash
# Navigate to project
cd "/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader"

# Install dependencies
pip install -r standalone/requirements.txt

# Run CLI
python cli.py --help
python cli.py brief
python cli.py score SPY
python cli.py arb
python cli.py positions

# Or use as module
python -m dexter --help
```

---

## Summary for Next Terminal

1. **Alpha Trader base exists** at `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/`
2. **Add Dexter CLI** using code in Section 6.1
3. **Add Volume Profile** using code in Section 6.2
4. **Add Order Flow** using code in Section 6.3
5. **Add A+ Scoring** using code in Section 6.4
6. **Add Arbitrage Scanner** using code in Section 6.5
7. **Add OANDA adapter** using code in Section 6.6
8. **Add Kalshi adapter** using code in Section 6.7
9. **Execute on**: OANDA (gold), Kalshi, Polymarket
10. **Signal-only for**: Futures, Schwab options

The core trading strategy is:
- **Volume Profile** for trade location
- **Order Flow** (CVD, delta, footprint) for confirmation
- **A+ Scoring** for deterministic trade grading
- **Risk Governor** for position sizing and limits

---

*End of Dexter Handoff Document*
