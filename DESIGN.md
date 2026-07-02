# Zynth-Level Architecture Design

> **Date:** January 8, 2026
> **Status:** Architecture Specification for Dexter Upgrade
> **Target:** Upgrade Dexter CLI to Zynth-level finance agent platform

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Overview](#architecture-overview)
3. [New Pipeline Design](#new-pipeline-design)
4. [Module Boundaries](#module-boundaries)
5. [Data Flow](#data-flow)
6. [Integration Points](#integration-points)

---

## Executive Summary

### Goal

Transform Dexter from a basic trading research system into a sophisticated, multi-layered finance agent platform with:

1. **Strict Separation:** Research → Decision → Control → Execution phases
2. **Plugin Architecture:** Strategy capsules for extensible trading logic
3. **Portfolio Intelligence:** Central brain for allocation, suppression, and risk management
4. **Deep Research:** Web content extraction with citations and evidence tracking
5. **Rich Reporting:** Grouped, ranked trade intents with clear entry/exit criteria

### Key Design Principles

- **Minimal Changes:** Extend existing YAML workflows, don't replace them
- **Risk Isolation:** No LLM can directly place orders; all pass through RiskGovernor
- **Backward Compatibility:** Preserve all existing adapters (OANDA, Kalshi, Polymarket, Schwab)
- **Serialization:** All new objects are JSON-serializable for audit logging
- **Deterministic:** Same inputs produce consistent, reproducible outputs

---

## Architecture Overview

### Current State (Before Upgrade)

```
┌─────────────────────────────────────────────────────────────┐
│                   DEXTER (CURRENT)                     │
├─────────────────────────────────────────────────────────────┤
│                                                     │
│  1. Data Collection (Tools/Agents)                    │
│     ├── Fetch options, futures, crypto, polymarket      │
│     ├── Calculate technicals, volume profile, order flow  │
│     └── Score setups (A+ system)                     │
│                                                     │
│  2. Brain (LLM)                                     │
│     ├── Gemini inference on market data                   │
│     ├── Generate trade recommendations                      │
│     └── Deep research critique                          │
│                                                     │
│  3. Reporting                                         │
│     ├── Generate morning report (markdown/html/text)       │
│     ├── Log executions to audit DB                       │
│     └── Calculate P&L                                  │
│                                                     │
│  4. Execution (via adapters)                           │
│     ├── OANDA (gold)                                   │
│     ├── Kalshi (prediction markets)                        │
│     ├── Polymarket (crypto)                              │
│     ├── Schwab (options, pending)                         │
│     └── Topstep (futures)                               │
└─────────────────────────────────────────────────────────────┘
```

### Target State (After Zynth Upgrade)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DEXTER (ZYNTH-LEVEL)                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  1. RESEARCH LAYER                                      │   │
│  │                                                           │   │
│  │  ├─ Web Ingestion Module                                 │   │
│  │  │  ├─ URL list → Extract text (trafilatura)      │   │
│  │  │  ├─ Store EvidenceItems (with citations)              │   │
│  │  │  └─ Summarize into ThesisObject                   │   │
│  │                                                           │   │
│  │  └─ Strategy Capsules (Plugin System)                      │   │
│  │     ├─ Base Capsule interface                           │   │
│  │     ├─ spy_qqq_liquidity_sweep (SPY/QQQ)           │   │
│  │     ├─ nq_session_trend (NQ futures, signal-only)    │   │
│  │     ├─ xauusd_macro_levels (gold, OANDA executable) │   │
│  │     └─ kalshi_macro_sensor (regime flags, bias)     │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  2. DECISION LAYER (PortfolioBrain)                   │   │
│  │                                                           │   │
│  │  ├─ Ranking: Score and rank all TradeIntents             │   │
│  │  ├─ Suppression: Remove correlated/duplicate intents       │   │
│  │  ├─ Sizing: Calculate position sizes (risk per trade)      │   │
│  │  └─ Risk Limits: Enforce max loss/day, max open risk   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  3. CONTROL LAYER (RiskGovernor + Router)              │   │
│  │                                                           │   │
│  │  ├─ RiskGovernor                                        │   │
│  │  │  ├─ Validate all orders before execution            │   │
│  │  │  ├─ Check account constraints (margin, PDT)      │   │
│  │  │  └─ Enforce stop loss rules                      │   │
│  │                                                           │   │
│  │  └─ Router (Execution Gating)                            │   │
│  │     ├─ AUTO: OANDA + Kalshi (when enabled)            │   │
│  │     ├─ CONFIRM: Generate order, wait for approval         │   │
│  │     └─ SIGNAL_ONLY: Never submit, only report           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  4. EXECUTION LAYER                                     │   │
│  │                                                           │   │
│  │  ExecutionPlans (from Router) → Broker Adapters            │   │
│  │  ├─ OANDA adapter (AUTO now for gold)                  │   │
│  │  ├─ Kalshi adapter (AUTO now for prediction markets)      │   │
│  │  ├─ Polymarket adapter (AUTO for crypto)                │   │
│  │  ├─ Schwab adapter (SIGNAL_ONLY until approved)          │   │
│  │  └─ Topstep adapter (SIGNAL_ONLY for futures)           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                           │                                       │
│                           ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  5. REPORTING LAYER                                    │   │
│  │                                                           │   │
│  │  ├─ Morning Report (upgraded)                              │   │
│  │  │  ├─ Grouped: Primary / Conditional / Signal-only │   │
│  │  │  ├─ Ranked: By conviction score                │   │
│  │  │  ├─ Each intent: Invalidation + Time stop        │   │
│  │  │  ├─ Payoff tables for options spreads          │   │
│  │  │  └─ Output: Markdown + JSON                   │   │
│  │                                                           │   │
│  │  └─ Audit Logging (existing pattern)                       │   │
│  │     └─ All actions serialized to JSON and stored        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## New Pipeline Design

### Enhanced Morning Report Workflow

```yaml
# New flow for morning-report.yaml
RESEARCH → CAPSULES → PORTFOLIO_BRAIN → RISK_GOVERNOR → ROUTER → REPORTING
```

#### Phase Breakdown

**1. RESEARCH (Ingest)**
```
URL List (CLI args) → [ResearchIngestion] → EvidenceItems[] + ThesisObject
```

**2. CAPSULES (Generate Intents)**
```
ThesisObject + Market Data → [Each Capsule] → TradeIntent[]
```

Each capsule:
- Analyzes market data
- Generates one or more TradeIntents
- Assigns conviction score
- Provides entry/exit criteria
- Cites evidence sources

**3. PORTFOLIO_BRAIN (Rank & Size)**
```
TradeIntent[] + Current Positions → [PortfolioBrain] → RankedTradeIntent[]
```

- Rank by conviction, regime alignment, portfolio fit
- Suppress correlated/duplicate intents
- Size positions based on risk limits
- Apply circuit breakers (consecutive losses, daily loss)

**4. RISK_GOVERNOR (Validate)**
```
RankedTradeIntent[] + Account State → [RiskGovernor] → RiskDecision[]
```

For each intent:
- Validate symbol, price, size
- Check margin requirements
- Apply risk limits
- Return approved/rejected decision

**5. ROUTER (Gate Execution)**
```
RiskDecision[] + Config → [Router] → ExecutionPlan[]
```

For each approved intent:
- Determine execution mode (AUTO/CONFIRM/SIGNAL_ONLY)
- Generate order payload
- Store in audit DB
- Return ExecutionPlan

**6. REPORTING (Render)**
```
ExecutionPlan[] → [Enhanced Reporter] → Markdown + JSON
```

- Group by category (Primary/Conditional/Signal-only)
- Rank within groups
- Include invalidation + time stop
- Add payoff tables for options
- Deliver via email/SMS/CLI

---

## Module Boundaries

### Core Data Models (models.py)

```python
@dataclass
class EvidenceItem:
    """Single piece of evidence with citation."""
    id: str                          # Unique ID
    url: str                          # Source URL
    title: str                         # Article/Source title
    snippet: str                       # Key excerpt
    timestamp: datetime                  # When published
    confidence: float                   # 0.0-1.0 reliability score
    tags: List[str]                    # E.g., ["macro", "earnings", "fed"]

@dataclass
class ThesisObject:
    """Synthesized thesis from evidence."""
    id: str                          # Unique ID
    summary: str                      # Concise thesis statement
    evidence_ids: List[str]            # References to EvidenceItems
    conviction: float                  # 0.0-1.0 overall conviction
    regime_bias: str                  # "risk_on", "risk_off", "neutral"
    created_at: datetime
    tags: List[str]

@dataclass
class TradeIntent:
    """Trade recommendation from a capsule."""
    id: str                          # Unique ID
    capsule_id: str                   # Which capsule generated this
    thesis_id: str                   # Which thesis this supports
    symbol: str
    direction: str                    # "long" or "short"
    entry_price: float
    stop_price: float
    target_price: float
    conviction: float                  # 0.0-1.0
    invalidation_price: float          # Price that invalidates thesis
    time_stop: datetime               # Max hold time
    risk_reward_ratio: float
    size: Optional[float]             # Set by PortfolioBrain
    execution_mode: str              # "AUTO", "CONFIRM", "SIGNAL_ONLY"
    venue: str                       # "oanda", "kalshi", "polymarket", etc.
    evidence_citations: List[str]      # IDs of supporting evidence
    created_at: datetime

@dataclass
class RiskDecision:
    """Risk governor's verdict on a trade intent."""
    intent_id: str
    approved: bool
    rejection_reason: Optional[str]
    risk_adjusted_size: Optional[float]
    warnings: List[str]
    checked_at: datetime

@dataclass
class ExecutionPlan:
    """Final execution plan ready for submission."""
    intent_id: str
    order_payload: dict              # Full order parameters for broker
    execution_mode: str              # "AUTO", "CONFIRM", "SIGNAL_ONLY"
    venue: str
    requires_confirmation: bool
    created_at: datetime
```

### Strategy Capsules (capsules/)

**Base Interface:**
```python
from abc import ABC, abstractmethod

class BaseCapsule(ABC):
    """Base class for all strategy capsules."""

    @property
    @abstractmethod
    def capsule_id(self) -> str:
        """Unique capsule identifier."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable capsule name."""
        pass

    @property
    @abstractmethod
    def symbols(self) -> List[str]:
        """Symbols this capsule monitors."""
        pass

    @property
    @abstractmethod
    def execution_mode(self) -> str:
        """Default execution mode: AUTO, CONFIRM, or SIGNAL_ONLY."""
        pass

    @abstractmethod
    async def generate_intents(
        self,
        thesis: ThesisObject,
        market_data: dict,
        **kwargs
    ) -> List[TradeIntent]:
        """
        Generate trade intents based on thesis and market data.

        Returns:
            List of TradeIntent objects
        """
        pass

    @abstractmethod
    async def validate_setup(
        self,
        symbol: str,
        current_price: float,
        **kwargs
    ) -> bool:
        """
        Validate if setup meets entry criteria.

        Returns:
            True if setup is valid
        """
        pass
```

**Starter Capsules:**

1. **spy_qqq_liquidity_sweep**
   - Symbols: SPY, QQQ
   - Execution: SIGNAL_ONLY (futures not supported)
   - Logic: Volume profile + order flow + liquidity sweep detection
   - Wrapped from existing scoring.py logic

2. **nq_session_trend**
   - Symbols: NQ (Nasdaq futures)
   - Execution: SIGNAL_ONLY (Topstep pending approval)
   - Logic: Session trend detection + momentum analysis
   - Technical-only, no LLM reasoning

3. **xauusd_macro_levels**
   - Symbols: XAUUSD (Gold)
   - Execution: AUTO (OANDA approved)
   - Logic: Macro level trading + regime alignment
   - Uses thesis + evidence for macro context

4. **kalshi_macro_sensor**
   - Symbols: Kalshi prediction markets
   - Execution: AUTO (Kalshi approved)
   - Logic: Regime detection + bias setting (risk-on/off)
   - Creates TradeIntents only when regime flags align

### Portfolio Brain (portfolio.py)

**Responsibilities:**

```python
class PortfolioBrain:
    """Central intelligence for portfolio-level decisions."""

    async def rank_intents(
        self,
        intents: List[TradeIntent],
        current_positions: dict,
        **kwargs
    ) -> List[TradeIntent]:
        """
        Rank and filter trade intents.

        1. Rank by conviction, regime alignment, portfolio fit
        2. Suppress correlated/duplicate intents
        3. Apply circuit breakers

        Returns:
            Ranked, filtered intents
        """
        pass

    async def suppress_duplicates(
        self,
        intents: List[TradeIntent]
    ) -> List[TradeIntent]:
        """
        Remove correlated or duplicate intents.

        - Same symbol + direction within time window
        - Highly correlated symbols (e.g., SPY/QQQ)
        """
        pass

    async def size_positions(
        self,
        intents: List[TradeIntent],
        account_value: float,
        **kwargs
    ) -> List[TradeIntent]:
        """
        Calculate optimal position sizes.

        Rules:
        - Max risk per trade (e.g., 0.5% of account)
        - Max loss per day (e.g., 2% of account)
        - Max open risk (e.g., 5% of account)
        - Adjust size based on grade/conviction
        """
        pass

    async def check_circuit_breakers(
        self,
        **kwargs
    ) -> bool:
        """
        Check if circuit breakers are triggered.

        Conditions:
        - Consecutive losses: Stop after 2
        - Daily loss limit: Stop if >2%
        - Prohibited windows: FOMC, CPI, NFP
        """
        pass
```

### Router (router.py)

**Execution Gating Logic:**

```python
class ExecutionRouter:
    """Routes trade intents to appropriate execution mode."""

    async def route_intents(
        self,
        risk_decisions: List[RiskDecision],
        config: dict,
        **kwargs
    ) -> List[ExecutionPlan]:
        """
        Convert risk decisions to execution plans.

        For each approved intent:
        1. Determine execution mode based on venue config
        2. Generate order payload for specific broker
        3. Set confirmation requirement
        4. Create ExecutionPlan

        Returns:
            List of ExecutionPlan objects
        """
        pass

    def determine_execution_mode(
        self,
        intent: TradeIntent,
        venue: str,
        config: dict
    ) -> str:
        """
        Determine AUTO vs CONFIRM vs SIGNAL_ONLY.

        Rules (from config.yaml):
        - OANDA: AUTO (if enabled)
        - Kalshi: AUTO (if enabled)
        - Polymarket: AUTO (small trades)
        - Schwab: CONFIRM (manual approval)
        - Topstep: SIGNAL_ONLY (no broker support yet)
        """
        pass

    def generate_order_payload(
        self,
        intent: TradeIntent,
        venue: str
    ) -> dict:
        """
        Generate venue-specific order payload.

        OANDA: { instrument, units, orderType, etc. }
        Kalshi: { ticker, side, count, etc. }
        Schwab: { symbol, quantity, orderType, etc. }
        """
        pass
```

### Research Ingestion (research.py)

**New Module:**

```python
class ResearchIngestion:
    """Web content extraction and thesis generation."""

    async def ingest_urls(
        self,
        urls: List[str],
        **kwargs
    ) -> tuple[List[EvidenceItem], ThesisObject]:
        """
        Extract content from URLs and synthesize thesis.

        1. Fetch HTML from each URL (trafilatura)
        2. Extract clean text
        3. Store EvidenceItems in DB
        4. Synthesize into ThesisObject (LLM)

        Returns:
            (EvidenceItems[], ThesisObject)
        """
        pass

    async def extract_content(
        self,
        url: str
    ) -> EvidenceItem:
        """
        Extract clean text from URL.

        Uses trafilatura (feature flag: ENABLE_RESEARCH_INGESTION)
        """
        pass

    async def generate_thesis(
        self,
        evidence_items: List[EvidenceItem]
    ) -> ThesisObject:
        """
        Synthesize evidence into a thesis object.

        Uses LLM (Gemini/OpenAI) to:
        - Summarize key points
        - Determine regime bias (risk-on/off)
        - Assign overall conviction
        """
        pass
```

---

## Data Flow

### Full Morning Report Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. CLI TRIGGER                                           │
│    dexter run research --urls [URL1, URL2, ...]        │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. RESEARCH INGESTION                                      │
│    URLs → Extract text → EvidenceItems → ThesisObject      │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. STRATEGY CAPSULES                                      │
│    ThesisObject + Market Data → TradeIntent[]               │
│    (Each capsule generates 0-2 intents)                     │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. PORTFOLIO BRAIN                                        │
│    TradeIntent[] + Current Positions → RankedTradeIntent[]     │
│    (Rank, suppress duplicates, size positions)                 │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. RISK GOVERNOR                                         │
│    RankedTradeIntent[] + Account State → RiskDecision[]       │
│    (Validate, check limits, approve/reject)                  │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. ROUTER                                                 │
│    RiskDecision[] + Config → ExecutionPlan[]                  │
│    (Determine AUTO/CONFIRM/SIGNAL_ONLY, generate payloads)   │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. REPORTING                                               │
│    ExecutionPlan[] → Markdown + JSON + Email/SMS               │
│    (Group, rank, format, deliver)                            │
└─────────────────────────────────────────────────────────────────┘
```

### Execution Mode Decision Tree

```
TradeIntent
    │
    ├─ Venue: OANDA
    │   ├─ Config: AUTO enabled?
    │   │   ├─ Yes → AUTO
    │   │   └─ No → CONFIRM
    │   └─ Exception: Large size (>2x normal) → CONFIRM
    │
    ├─ Venue: Kalshi
    │   ├─ Config: AUTO enabled?
    │   │   ├─ Yes → AUTO
    │   │   └─ No → CONFIRM
    │   └─ Exception: Low liquidity (< $1000) → CONFIRM
    │
    ├─ Venue: Polymarket
    │   └─ Size < 0.5 ETH → AUTO, else CONFIRM
    │
    ├─ Venue: Schwab
    │   └─ Always CONFIRM (manual approval required)
    │
    └─ Venue: Topstep
        └─ Always SIGNAL_ONLY (no API execution yet)
```

---

## Integration Points

### 1. Workflow Integration (morning_report.yaml)

```yaml
# Extend existing morning_report.yaml with new nodes

# New nodes added to workflow:
- id: ingest-research
  name: Ingest Research URLs
  phase: Plan
  skill_id: ingest_research
  inputs: [research_urls]
  outputs: [evidence_items, thesis_object]
  tools: [ingest_research]

- id: run-capsules
  name: Generate Trade Intents from Capsules
  phase: Plan
  skill_id: run_capsules
  inputs: [thesis_object, market_data]
  outputs: [trade_intents]
  tools: [run_capsules]

- id: portfolio-brain
  name: Rank and Size Intents
  phase: Plan
  skill_id: portfolio_brain
  inputs: [trade_intents, current_positions]
  outputs: [ranked_intents]
  tools: [portfolio_brain]

- id: risk-governor
  name: Validate and Approve Intents
  phase: Plan
  skill_id: risk_governor
  inputs: [ranked_intents, account_state]
  outputs: [risk_decisions]
  tools: [risk_governor]

- id: router
  name: Generate Execution Plans
  phase: Plan
  skill_id: router
  inputs: [risk_decisions, config]
  outputs: [execution_plans]
  tools: [router]

# Updated format-report node to handle new format
- id: format-report
  name: Format Enhanced Report
  phase: Build
  skill_id: generate_report
  inputs: [execution_plans]
  outputs: [formatted_reports]
  tools: [generate_report]
```

### 2. Tool Registry Updates (tool_registry.yaml)

```yaml
# New tools added:

- id: ingest_research
  name: Ingest Research from URLs
  tier: T1
  category: research
  provider: local
  parameters:
    - { name: urls, type: array, required: true }
  implementation:
    standalone: research.ingest_urls

- id: run_capsules
  name: Run Strategy Capsules
  tier: T1
  category: strategy
  provider: local
  parameters:
    - { name: capsule_ids, type: array, default: ["all"] }
  implementation:
    standalone: capsules.run_all_capsules

- id: portfolio_brain
  name: Portfolio Brain Ranking
  tier: T2
  category: strategy
  provider: local
  parameters:
    - { name: trade_intents, type: array, required: true }
  implementation:
    standalone: portfolio.rank_and_size

- id: risk_governor
  name: Risk Governor Validation
  tier: T3
  category: strategy
  provider: local
  parameters:
    - { name: intents, type: array, required: true }
  implementation:
    standalone: router.risk_governor_validate

- id: router
  name: Execution Router
  tier: T3
  category: execution
  provider: local
  parameters:
    - { name: risk_decisions, type: array, required: true }
  implementation:
    standalone: router.route_intents
```

### 3. CLI Commands Added (cli.py)

```python
# New commands added to Typer CLI

@app.command()
def run(
    workflow: str = typer.Argument(..., help="Workflow: morning-report, research")
    urls: List[str] = typer.Option([], "--urls", "-u", help="Research URLs"),
    **kwargs
):
    """Run workflow."""
    if workflow == "research":
        asyncio.run(run_research_workflow(urls))
    elif workflow == "morning-report":
        asyncio.run(run_morning_report_workflow())

@app.command()
def approve(intent_id: str = typer.Argument(...)):
    """Manually approve a pending trade intent."""
    asyncio.run(manually_approve_intent(intent_id))

@app.command()
def reject(intent_id: str = typer.Argument(...)):
    """Manually reject a pending trade intent."""
    asyncio.run(manually_reject_intent(intent_id))
```

### 4. Database Schema Extensions

```sql
-- New tables added to audit.db

CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    title TEXT,
    snippet TEXT,
    timestamp TEXT NOT NULL,
    confidence REAL,
    tags TEXT,  -- JSON array as string
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis_objects (
    id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    evidence_ids TEXT,  -- JSON array as string
    conviction REAL,
    regime_bias TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_intents (
    id TEXT PRIMARY KEY,
    capsule_id TEXT NOT NULL,
    thesis_id TEXT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL,
    stop_price REAL,
    target_price REAL,
    conviction REAL,
    invalidation_price REAL,
    time_stop TEXT,
    risk_reward_ratio REAL,
    size REAL,
    execution_mode TEXT,
    venue TEXT,
    evidence_citations TEXT,  -- JSON array as string
    status TEXT,  -- 'pending', 'approved', 'rejected', 'executed', 'closed'
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS execution_plans (
    id TEXT PRIMARY KEY,
    intent_id TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    venue TEXT NOT NULL,
    order_payload TEXT NOT NULL,  -- JSON object as string
    requires_confirmation BOOLEAN,
    status TEXT,  -- 'pending', 'submitted', 'filled', 'cancelled'
    created_at TEXT NOT NULL
);
```

### 5. Configuration Updates (config.yaml)

```yaml
# New config sections added

research:
  enable_ingestion: true  # Feature flag for trafilatura
  max_urls_per_batch: 10
  evidence_confidence_threshold: 0.7

capsules:
  enabled:
    - spy_qqq_liquidity_sweep
    - nq_session_trend
    - xauusd_macro_levels
    - kalshi_macro_sensor

portfolio:
  max_risk_per_trade_pct: 0.5
  max_loss_per_day_pct: 2.0
  max_open_risk_pct: 5.0
  consecutive_loss_limit: 2
  correlation_threshold: 0.7

execution_modes:
  venues:
    oanda:
      auto_enabled: true
      max_size_auto: 10000
    kalshi:
      auto_enabled: true
      max_size_auto: 5000
    polymarket:
      auto_enabled: true
      max_size_auto: 100  # in ETH
    schwab:
      auto_enabled: false  # Always CONFIRM
    topstep:
      auto_enabled: false  # Always SIGNAL_ONLY

router:
  confirmation_timeout_hours: 4
  retry_failed_orders: true
  max_retry_attempts: 3
```

---

## Quality & Safety Guarantees

### Deterministic Behavior

- **Same Inputs → Same Outputs:** Given identical market data, capsules produce identical TradeIntents
- **Ranking Stability:** PortfolioBrain uses deterministic scoring, no randomness
- **Routing Predictable:** Router decisions are rule-based, not probabilistic

### Graceful Degradation

- **External Data Failure:**
  - URLs unreachable → Mark evidence quality low, continue with technical analysis
  - Broker API down → Fall back to SIGNAL_ONLY mode
  - LLM timeout → Use cached responses or skip thesis generation

- **Feature Flags:**
  - `ENABLE_RESEARCH_INGESTION`: Disable URL extraction if trafilatura unavailable
  - `AUTO_EXECUTION_ENABLED`: Global toggle for AUTO mode
  - `CAPSULE_DEBUG_MODE`: Run capsules in isolation for testing

### Risk Isolation

- **No Direct LLM Execution:**
  - All orders generated from structured TradeIntents
  - Router validates against RiskGovernor
  - RiskGovernor enforces account constraints

- **Audit Trail:**
  - Every TradeIntent logged before any execution
  - All ExecutionPlans stored in audit DB
  - Every LLM call logged with prompt + response

- **Circuit Breakers:**
  - Stop trading after 2 consecutive losses
  - Stop for day if loss >2%
  - Block trades 30min before/after major news (FOMC, CPI, NFP)

---

## Implementation Order

1. ✅ DESIGN.md (this document)
2. ⏳ models.py (data schemas)
3. ⏳ capsules/ directory + base class
4. ⏳ 4 starter capsules
5. ⏳ portfolio.py (PortfolioBrain)
6. ⏳ router.py (execution gating)
7. ⏳ research.py (ingestion module)
8. ⏳ Enhanced reporting.py
9. ⏳ CLI command updates
10. ⏳ Workflow integration
11. ⏳ Tests
12. ⏳ Config updates

---

## Summary

This design transforms Dexter into a modular, extensible finance agent platform with:

✅ **Strict Phase Separation:** Research → Decision → Control → Execution
✅ **Plugin Architecture:** Easy to add new capsules without changing core
✅ **Portfolio Intelligence:** Central brain for risk management and sizing
✅ **Deep Research:** Evidence-backed theses with citations
✅ **Rich Reporting:** Grouped, ranked, actionable trade recommendations
✅ **Risk Control:** No LLM can bypass RiskGovernor
✅ **Backward Compatible:** All existing adapters and workflows preserved
✅ **Production Ready:** Graceful degradation, feature flags, audit logging

The upgrade maintains Dexter's simplicity while adding Zynth-level sophistication.
