# Alpha Trader Agent System - Complete Handoff

> **Date:** January 4, 2026
> **Status:** Architecture Complete, Ready for Implementation
> **Location:** `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/`

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Architecture](#system-architecture)
3. [Agent Templates (Full YAML)](#agent-templates)
4. [Workflow Definitions (Full YAML)](#workflow-definitions)
5. [Tool Registry (Full YAML)](#tool-registry)
6. [Standalone Implementation Plan](#standalone-implementation)
7. [API Integration Details](#api-integration)
8. [Step-by-Step Build Instructions](#build-instructions)
9. [A2rchitech Migration Path](#migration-path)

---

## 1. Executive Summary

### What This System Does

Alpha Trader is a multi-agent trading research and execution system that:

1. **Daily Research (4 AM ET):** Collects overnight data from options chains, futures, crypto exchanges, and Polymarket prediction markets
2. **Morning Reports (6 AM ET):** Generates actionable trade recommendations delivered via email/SMS/iMessage
3. **Algorithmic Execution:** Executes trades via broker APIs (Interactive Brokers, Schwab)
4. **Continuous Monitoring:** Tracks positions, stops, and alerts during market hours

### Why This Architecture

The system follows A2rchitech patterns exactly so that:
- **Zero Drift:** YAML schemas match A2rchitech JSON schemas 1:1
- **Standalone Today:** Works immediately with Python + APScheduler
- **Seamless Migration:** When A2rchitech platform is ready, configs port directly without changes

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Multi-agent design | Separation of concerns (research vs execution vs audit) |
| YAML-first config | Matches A2rchitech schema, human-readable |
| Python standalone | Fast iteration, rich trading libraries |
| Scientific loop phases | OBSERVE→THINK→PLAN→EXECUTE→VERIFY matches A2rchitech |
| Tiered permissions | T0-T4 tiers match A2rchitech policy engine |

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ALPHA TRADER SYSTEM                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         AGENT LAYER                                    │  │
│  │                                                                        │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │  │
│  │  │  RESEARCH   │  │  ANALYSIS   │  │  STRATEGY   │  │  EXECUTION  │  │  │
│  │  │   AGENT     │  │   AGENT     │  │   AGENT     │  │   AGENT     │  │  │
│  │  │             │  │             │  │             │  │             │  │  │
│  │  │ Phase:      │  │ Phase:      │  │ Phase:      │  │ Phase:      │  │  │
│  │  │ OBSERVE     │  │ THINK       │  │ PLAN        │  │ EXECUTE     │  │  │
│  │  │             │  │             │  │             │  │             │  │  │
│  │  │ Fetches:    │  │ Processes:  │  │ Generates:  │  │ Submits:    │  │  │
│  │  │ - Options   │  │ - Signals   │  │ - Trades    │  │ - Orders    │  │  │
│  │  │ - Futures   │  │ - Patterns  │  │ - Sizing    │  │ - Stops     │  │  │
│  │  │ - Crypto    │  │ - Greeks    │  │ - Risk      │  │ - Targets   │  │  │
│  │  │ - Polymarket│  │ - Sentiment │  │ - Timing    │  │             │  │  │
│  │  │ - News      │  │             │  │             │  │             │  │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘  │  │
│  │                                                                        │  │
│  │  ┌─────────────┐                                                      │  │
│  │  │   AUDITOR   │  Phase: VERIFY + LEARN                               │  │
│  │  │   AGENT     │  Logs all executions, tracks P&L, extracts learnings │  │
│  │  └─────────────┘                                                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      ORCHESTRATOR (Scheduler)                          │  │
│  │                                                                        │  │
│  │  APScheduler (standalone) → A2rchitech Workflow Engine (future)       │  │
│  │                                                                        │  │
│  │  Schedules:                                                            │  │
│  │  - 04:00 ET: daily-research-cycle                                     │  │
│  │  - 06:00 ET: morning-report                                           │  │
│  │  - Every 5m: continuous-monitoring (market hours only)                │  │
│  │  - On-demand: trade-execution                                         │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         TOOL LAYER                                     │  │
│  │                                                                        │  │
│  │  Market Data:          Analysis:           Execution:                 │  │
│  │  ├─ fetch_options      ├─ calc_technicals  ├─ submit_order           │  │
│  │  ├─ fetch_futures      ├─ calc_greeks      ├─ modify_order           │  │
│  │  ├─ fetch_crypto       ├─ eval_sentiment   ├─ cancel_order           │  │
│  │  ├─ fetch_polymarket   ├─ detect_patterns  └─ emergency_close        │  │
│  │  └─ fetch_news         └─ calc_correlations                          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         DATA LAYER                                     │  │
│  │                                                                        │  │
│  │  SQLite databases:                                                    │  │
│  │  ├─ market_data.db    (cached market data)                           │  │
│  │  ├─ positions.db      (current positions, P&L)                       │  │
│  │  ├─ research.db       (research findings cache)                      │  │
│  │  └─ audit.db          (append-only execution log)                    │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Agent Templates (Full YAML)

Create file: `agent_templates.yaml`

```yaml
# Alpha Trader Agent Templates
# Schema: A2rchitech Agent Template Schema v1.0
# Location: /Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/agent_templates.yaml

version: "1.0"

agent_templates:
  # ============================================================================
  # RESEARCH AGENT - Data Collection & Market Observation
  # ============================================================================
  - id: alpha-research-agent-v1
    name: Alpha Research Agent
    description: |
      Collects market data from multiple sources including options chains,
      futures markets, cryptocurrency exchanges, and prediction markets.
      Runs daily at 4 AM ET to gather overnight data for analysis.
    version: "1.0.0"
    tenant_id: alpha-trader

    persona_overlay:
      role: researcher
      goal: |
        Collect comprehensive market data across all asset classes to identify
        potential trading opportunities. Focus on unusual activity, significant
        price movements, and emerging trends.
      backstory: |
        You are a quantitative research analyst with expertise in multi-asset
        market analysis. You have access to options flow data, futures markets,
        cryptocurrency exchanges, and prediction markets. Your job is to
        systematically collect and organize market data for downstream analysis.
      constraints:
        - Never execute trades directly
        - Always cite data sources
        - Flag data quality issues immediately
        - Respect API rate limits
      provider_preferences:
        priority_order:
          - openai
          - anthropic
        fallback_timeout: 30

    traits:
      - data-collector
      - multi-asset
      - systematic

    roles:
      - researcher
      - observer

    default_workflow_refs:
      - daily-research-cycle-v1

    skill_policy:
      allowed_skill_tiers:
        - T0
        - T1
        - T2
      allowed_tools:
        - fetch_options_chain
        - fetch_futures_data
        - fetch_crypto_data
        - fetch_polymarket
        - fetch_news
        - fetch_sentiment
        - store_research
      denied_tools:
        - submit_order
        - modify_order
        - cancel_order
        - emergency_close

  # ============================================================================
  # ANALYSIS AGENT - Signal Generation & Pattern Recognition
  # ============================================================================
  - id: alpha-analysis-agent-v1
    name: Alpha Analysis Agent
    description: |
      Processes raw market data into actionable signals. Performs technical
      analysis, options Greeks calculation, sentiment analysis, and pattern
      detection across all collected data.
    version: "1.0.0"
    tenant_id: alpha-trader

    persona_overlay:
      role: analyst
      goal: |
        Transform raw market data into clear, actionable trading signals.
        Identify patterns, calculate risk metrics, and quantify sentiment
        to support trade decision-making.
      backstory: |
        You are a senior quantitative analyst specializing in signal generation.
        You combine technical analysis, options theory, and sentiment analysis
        to produce high-conviction trade signals. You understand market
        microstructure and can identify when signals are reliable vs noise.
      constraints:
        - All signals must have confidence scores
        - Document assumptions clearly
        - Flag conflicting signals
        - Never recommend position sizes (that's Strategy Agent's job)
      provider_preferences:
        priority_order:
          - openai
          - anthropic
        fallback_timeout: 60

    traits:
      - quantitative
      - pattern-recognition
      - signal-generation

    roles:
      - analyst
      - thinker

    default_workflow_refs:
      - daily-research-cycle-v1

    skill_policy:
      allowed_skill_tiers:
        - T0
        - T1
      allowed_tools:
        - calculate_technicals
        - analyze_options_greeks
        - evaluate_sentiment
        - detect_patterns
        - calculate_correlations
        - read_research
      denied_tools:
        - submit_order
        - modify_order
        - cancel_order
        - emergency_close

  # ============================================================================
  # STRATEGY AGENT - Trade Ideation & Risk Management
  # ============================================================================
  - id: alpha-strategy-agent-v1
    name: Alpha Strategy Agent
    description: |
      Generates specific trade recommendations with entry/exit criteria,
      position sizing, and risk parameters. Evaluates portfolio-level risk
      and ensures trades fit within defined risk limits.
    version: "1.0.0"
    tenant_id: alpha-trader

    persona_overlay:
      role: strategist
      goal: |
        Convert analysis signals into specific, actionable trade recommendations.
        Define precise entry points, stop losses, profit targets, and position
        sizes that respect portfolio risk limits.
      backstory: |
        You are a portfolio strategist with deep experience in position
        management and risk control. You understand Kelly criterion, risk
        parity, and portfolio construction. You never recommend trades that
        would breach risk limits, and you always define clear exit criteria.
      constraints:
        - Never exceed max_position_pct (5%)
        - Always define stop loss before entry
        - Risk/reward must be >= 2:1 for new positions
        - Maximum 10 concurrent positions
        - Daily loss limit: 2% of portfolio
      provider_preferences:
        priority_order:
          - anthropic
          - openai
        fallback_timeout: 45

    traits:
      - risk-aware
      - systematic
      - disciplined

    roles:
      - strategist
      - planner

    default_workflow_refs:
      - daily-research-cycle-v1
      - trade-execution-v1

    skill_policy:
      allowed_skill_tiers:
        - T0
        - T1
        - T2
      allowed_tools:
        - generate_trade_idea
        - calculate_position_size
        - define_risk_params
        - backtest_strategy
        - evaluate_portfolio_risk
        - read_research
        - read_analysis
      denied_tools:
        - submit_order
        - emergency_close

  # ============================================================================
  # EXECUTION AGENT - Order Management & Trade Execution
  # ============================================================================
  - id: alpha-execution-agent-v1
    name: Alpha Execution Agent
    description: |
      Executes approved trades via broker APIs. Manages order lifecycle,
      monitors fills, handles partial fills, and can execute emergency
      position closes when stop conditions are triggered.
    version: "1.0.0"
    tenant_id: alpha-trader

    persona_overlay:
      role: executor
      goal: |
        Execute trades efficiently with minimal slippage. Monitor order status,
        handle partial fills appropriately, and maintain accurate position
        records. Execute emergency stops without hesitation when triggered.
      backstory: |
        You are an execution trader with experience in algorithmic order
        management. You understand market microstructure, order types, and
        execution quality metrics. You prioritize capital preservation and
        will always execute stops before questioning them.
      constraints:
        - Only execute pre-approved trades
        - Log every order action immediately
        - Never override stop losses
        - Verify position after each fill
        - Maximum order size limits apply
      provider_preferences:
        priority_order:
          - openai
        fallback_timeout: 15

    traits:
      - disciplined
      - fast
      - reliable

    roles:
      - executor
      - trader

    default_workflow_refs:
      - trade-execution-v1
      - continuous-monitoring-v1

    skill_policy:
      allowed_skill_tiers:
        - T0
        - T1
        - T2
        - T3
        - T4
      allowed_tools:
        - submit_order
        - modify_order
        - cancel_order
        - get_positions
        - get_order_status
        - emergency_close
      denied_tools: []

  # ============================================================================
  # AUDITOR AGENT - Compliance & Performance Tracking
  # ============================================================================
  - id: alpha-auditor-agent-v1
    name: Alpha Auditor Agent
    description: |
      Maintains immutable audit logs of all system actions. Tracks P&L,
      analyzes execution quality, generates compliance reports, and
      extracts learnings for system improvement.
    version: "1.0.0"
    tenant_id: alpha-trader

    persona_overlay:
      role: auditor
      goal: |
        Maintain complete, immutable records of all trading activity.
        Analyze performance, identify areas for improvement, and ensure
        all actions are properly documented for compliance.
      backstory: |
        You are a compliance officer and performance analyst. You believe
        in radical transparency and complete documentation. Every trade,
        every decision, every outcome must be recorded and analyzed.
        You identify patterns in wins and losses to improve the system.
      constraints:
        - Never modify historical records
        - Log failures as thoroughly as successes
        - Flag any policy violations immediately
        - Generate daily performance summaries
      provider_preferences:
        priority_order:
          - openai
        fallback_timeout: 30

    traits:
      - thorough
      - compliant
      - analytical

    roles:
      - auditor
      - verifier

    default_workflow_refs:
      - continuous-monitoring-v1

    skill_policy:
      allowed_skill_tiers:
        - T0
        - T1
      allowed_tools:
        - log_execution
        - calculate_pnl
        - verify_fill_quality
        - generate_report
        - extract_learnings
        - read_audit_log
      denied_tools:
        - submit_order
        - modify_order
        - cancel_order
        - emergency_close
```

---

## 4. Workflow Definitions (Full YAML)

### Workflow 1: Daily Research Cycle

Create file: `workflows/daily_research_cycle.yaml`

```yaml
# Daily Research Cycle Workflow
# Schema: A2rchitech Workflow Definition Schema v1.0
# Schedule: Every day at 4:00 AM ET

version: "1.0"

workflow:
  id: daily-research-cycle-v1
  name: Daily Research Cycle
  description: |
    Comprehensive daily market research workflow that collects data from
    all sources, analyzes for signals, and generates trade recommendations.
    Runs pre-market to prepare for the trading day.
  version: "1.0.0"
  tenant_id: alpha-trader

  required_tiers:
    - T0
    - T1
    - T2

  success_criteria: |
    Research complete with: (1) data from all 5 sources collected,
    (2) at least 3 signals generated, (3) morning report queued

  failure_modes:
    - api_timeout: Retry with exponential backoff, max 3 attempts
    - data_quality: Flag and continue with available data
    - llm_error: Use fallback model, reduce complexity

  phases_used:
    - Observe
    - Think
    - Plan

  # ============================================================================
  # WORKFLOW NODES
  # ============================================================================
  nodes:
    # --------------------------------------------------------------------------
    # OBSERVE PHASE - Data Collection
    # --------------------------------------------------------------------------
    - id: fetch-options-data
      name: Fetch Options Chain Data
      phase: Observe
      skill_id: fetch_options_chain
      description: |
        Collect options chain data for watched symbols including:
        - Full chain (all strikes, all expirations)
        - Greeks (delta, gamma, theta, vega)
        - Open interest and volume
        - Unusual activity flags
      instructions: |
        1. Load watchlist from config
        2. For each symbol, fetch full options chain
        3. Calculate implied volatility surface
        4. Flag unusual OI/volume patterns
        5. Store raw data to research cache
      inputs:
        - watchlist
        - previous_day_data
      outputs:
        - options_chain_data
        - unusual_activity_flags
      tools:
        - fetch_options_chain
        - store_research
      constraints:
        time_budget: 300
        resource_limits:
          memory: "512Mi"
      expected_output_schema:
        type: object
        required:
          - symbols_fetched
          - data_quality_score
          - unusual_activity_count

    - id: fetch-futures-data
      name: Fetch Futures Market Data
      phase: Observe
      skill_id: fetch_futures_data
      description: |
        Collect futures data for major contracts:
        - ES (S&P 500), NQ (Nasdaq), YM (Dow)
        - CL (Crude Oil), GC (Gold), SI (Silver)
        - ZB (30Y Bond), ZN (10Y Note)
      instructions: |
        1. Connect to futures data feed
        2. Fetch overnight price action
        3. Calculate key levels (VPOC, VAH, VAL)
        4. Note any significant gaps
        5. Store to research cache
      inputs:
        - futures_watchlist
      outputs:
        - futures_data
        - key_levels
      tools:
        - fetch_futures_data
        - store_research
      constraints:
        time_budget: 180

    - id: fetch-crypto-data
      name: Fetch Cryptocurrency Data
      phase: Observe
      skill_id: fetch_crypto_data
      description: |
        Collect crypto data via CCXT from multiple exchanges:
        - BTC, ETH, SOL, major altcoins
        - Funding rates, open interest
        - Exchange flows, whale movements
      instructions: |
        1. Initialize CCXT with exchange configs
        2. Fetch OHLCV for watched pairs
        3. Collect funding rate data
        4. Check for large transfers
        5. Store to research cache
      inputs:
        - crypto_watchlist
        - exchange_list
      outputs:
        - crypto_data
        - funding_rates
        - whale_alerts
      tools:
        - fetch_crypto_data
        - store_research
      constraints:
        time_budget: 240

    - id: fetch-polymarket-data
      name: Fetch Prediction Market Data
      phase: Observe
      skill_id: fetch_polymarket
      description: |
        Collect prediction market data from Polymarket:
        - Active markets and current prices
        - Volume and liquidity metrics
        - Price movements and trends
      instructions: |
        1. Query Polymarket CLOB API
        2. Fetch active event contracts
        3. Calculate implied probabilities
        4. Identify mispriced markets
        5. Store to research cache
      inputs:
        - polymarket_watchlist
      outputs:
        - prediction_market_data
        - mispricing_alerts
      tools:
        - fetch_polymarket
        - store_research
      constraints:
        time_budget: 120

    - id: fetch-news-sentiment
      name: Fetch News and Sentiment
      phase: Observe
      skill_id: fetch_news
      description: |
        Collect overnight news and social sentiment:
        - Financial news headlines
        - Earnings announcements
        - Economic calendar events
        - Social sentiment scores
      instructions: |
        1. Query news APIs for overnight headlines
        2. Filter for watched symbols
        3. Score sentiment per headline
        4. Aggregate sentiment scores
        5. Store to research cache
      inputs:
        - news_sources
        - symbol_watchlist
      outputs:
        - news_data
        - sentiment_scores
      tools:
        - fetch_news
        - fetch_sentiment
        - store_research
      constraints:
        time_budget: 180

    # --------------------------------------------------------------------------
    # THINK PHASE - Analysis
    # --------------------------------------------------------------------------
    - id: analyze-technicals
      name: Technical Analysis
      phase: Think
      skill_id: calculate_technicals
      description: |
        Run technical analysis on all collected price data:
        - Moving averages (SMA, EMA)
        - Momentum indicators (RSI, MACD, Stochastics)
        - Volatility (ATR, Bollinger Bands)
        - Support/resistance levels
      instructions: |
        1. Load price data from research cache
        2. Calculate indicator values
        3. Identify trend direction
        4. Flag oversold/overbought conditions
        5. Output signal scores
      inputs:
        - options_chain_data
        - futures_data
        - crypto_data
      outputs:
        - technical_signals
        - trend_scores
      tools:
        - calculate_technicals
      constraints:
        time_budget: 120

    - id: analyze-options-flow
      name: Options Flow Analysis
      phase: Think
      skill_id: analyze_options_greeks
      description: |
        Deep analysis of options flow and positioning:
        - Net delta exposure
        - Gamma exposure (dealer hedging)
        - Put/call ratios
        - Skew analysis
      instructions: |
        1. Load options data
        2. Calculate aggregate Greeks
        3. Identify significant positioning
        4. Flag potential gamma squeezes
        5. Output flow signals
      inputs:
        - options_chain_data
        - unusual_activity_flags
      outputs:
        - options_flow_signals
        - positioning_summary
      tools:
        - analyze_options_greeks
      constraints:
        time_budget: 120

    - id: analyze-sentiment
      name: Sentiment Analysis
      phase: Think
      skill_id: evaluate_sentiment
      description: |
        Synthesize sentiment across all sources:
        - News sentiment aggregation
        - Social media sentiment
        - Options sentiment (put/call)
        - Prediction market implied sentiment
      instructions: |
        1. Load all sentiment data
        2. Weight by source reliability
        3. Calculate composite score
        4. Identify sentiment extremes
        5. Output sentiment signals
      inputs:
        - news_data
        - sentiment_scores
        - prediction_market_data
      outputs:
        - composite_sentiment
        - sentiment_signals
      tools:
        - evaluate_sentiment
      constraints:
        time_budget: 90

    - id: detect-patterns
      name: Pattern Detection
      phase: Think
      skill_id: detect_patterns
      description: |
        Identify actionable patterns across data:
        - Chart patterns (H&S, triangles, etc.)
        - Cross-asset correlations
        - Divergences (price vs indicators)
        - Unusual combinations
      instructions: |
        1. Run pattern recognition algorithms
        2. Score pattern quality
        3. Calculate breakout levels
        4. Identify correlation breaks
        5. Output pattern signals
      inputs:
        - technical_signals
        - options_flow_signals
        - composite_sentiment
      outputs:
        - pattern_signals
        - correlation_analysis
      tools:
        - detect_patterns
        - calculate_correlations
      constraints:
        time_budget: 150

    # --------------------------------------------------------------------------
    # PLAN PHASE - Trade Recommendations
    # --------------------------------------------------------------------------
    - id: generate-trade-ideas
      name: Generate Trade Ideas
      phase: Plan
      skill_id: generate_trade_idea
      description: |
        Synthesize all analysis into specific trade recommendations:
        - Entry criteria and price levels
        - Stop loss levels
        - Profit targets
        - Time horizon
        - Conviction level
      instructions: |
        1. Aggregate all signals
        2. Rank by conviction score
        3. Filter by risk/reward (min 2:1)
        4. Generate specific trade specs
        5. Output trade recommendations
      inputs:
        - technical_signals
        - options_flow_signals
        - sentiment_signals
        - pattern_signals
      outputs:
        - trade_recommendations
      tools:
        - generate_trade_idea
        - calculate_position_size
        - define_risk_params
      constraints:
        time_budget: 180

    - id: evaluate-portfolio-fit
      name: Evaluate Portfolio Fit
      phase: Plan
      skill_id: evaluate_portfolio_risk
      description: |
        Check trade recommendations against portfolio constraints:
        - Current position exposure
        - Sector concentration
        - Correlation with existing positions
        - Total portfolio risk
      instructions: |
        1. Load current portfolio state
        2. Simulate adding each trade
        3. Check against risk limits
        4. Adjust sizing if needed
        5. Output approved trades
      inputs:
        - trade_recommendations
        - current_positions
      outputs:
        - approved_trades
        - portfolio_risk_assessment
      tools:
        - evaluate_portfolio_risk
      constraints:
        time_budget: 120

    - id: queue-morning-report
      name: Queue Morning Report
      phase: Plan
      skill_id: generate_report
      description: |
        Compile all findings into morning report format:
        - Market summary
        - Key signals
        - Trade recommendations
        - Risk warnings
      instructions: |
        1. Aggregate all analysis outputs
        2. Format into report template
        3. Prioritize by importance
        4. Queue for delivery at 6 AM
        5. Store report artifact
      inputs:
        - approved_trades
        - technical_signals
        - sentiment_signals
        - portfolio_risk_assessment
      outputs:
        - morning_report
      tools:
        - generate_report
      constraints:
        time_budget: 120

  # ============================================================================
  # WORKFLOW EDGES (DAG)
  # ============================================================================
  edges:
    # Observe phase runs in parallel
    - from: fetch-options-data
      to: analyze-technicals
    - from: fetch-options-data
      to: analyze-options-flow
    - from: fetch-futures-data
      to: analyze-technicals
    - from: fetch-crypto-data
      to: analyze-technicals
    - from: fetch-polymarket-data
      to: analyze-sentiment
    - from: fetch-news-sentiment
      to: analyze-sentiment

    # Think phase has dependencies
    - from: analyze-technicals
      to: detect-patterns
    - from: analyze-options-flow
      to: detect-patterns
    - from: analyze-sentiment
      to: detect-patterns

    # Plan phase
    - from: detect-patterns
      to: generate-trade-ideas
    - from: generate-trade-ideas
      to: evaluate-portfolio-fit
    - from: evaluate-portfolio-fit
      to: queue-morning-report
```

### Workflow 2: Morning Report

Create file: `workflows/morning_report.yaml`

```yaml
# Morning Report Workflow
# Schema: A2rchitech Workflow Definition Schema v1.0
# Schedule: Every day at 6:00 AM ET

version: "1.0"

workflow:
  id: morning-report-v1
  name: Morning Report Generation
  description: |
    Generates and delivers the morning trading briefing with market summary,
    signals, and trade recommendations. Delivers via configured channels.
  version: "1.0.0"
  tenant_id: alpha-trader

  required_tiers:
    - T0
    - T1

  success_criteria: |
    Report delivered successfully to at least one channel

  failure_modes:
    - delivery_failure: Retry 3x, then escalate
    - missing_data: Generate partial report with warnings

  phases_used:
    - Plan
    - Build
    - Execute

  nodes:
    - id: load-report-data
      name: Load Report Data
      phase: Plan
      skill_id: read_research
      description: Load queued morning report from research cycle
      inputs:
        - morning_report_queue
      outputs:
        - report_data
      tools:
        - read_research
      constraints:
        time_budget: 30

    - id: format-report
      name: Format Report
      phase: Build
      skill_id: generate_report
      description: |
        Format report for delivery:
        - Plain text for SMS/iMessage
        - HTML for email
        - Markdown for storage
      inputs:
        - report_data
      outputs:
        - formatted_reports
      tools:
        - generate_report
      constraints:
        time_budget: 60

    - id: deliver-email
      name: Deliver via Email
      phase: Execute
      skill_id: send_email
      description: Send HTML report via email
      inputs:
        - formatted_reports
      outputs:
        - email_delivery_status
      tools:
        - send_email
      constraints:
        time_budget: 30

    - id: deliver-sms
      name: Deliver via SMS
      phase: Execute
      skill_id: send_sms
      description: Send condensed report via SMS
      inputs:
        - formatted_reports
      outputs:
        - sms_delivery_status
      tools:
        - send_sms
      constraints:
        time_budget: 30

    - id: log-delivery
      name: Log Delivery Status
      phase: Execute
      skill_id: log_execution
      description: Record delivery status in audit log
      inputs:
        - email_delivery_status
        - sms_delivery_status
      outputs:
        - delivery_log
      tools:
        - log_execution
      constraints:
        time_budget: 15

  edges:
    - from: load-report-data
      to: format-report
    - from: format-report
      to: deliver-email
    - from: format-report
      to: deliver-sms
    - from: deliver-email
      to: log-delivery
    - from: deliver-sms
      to: log-delivery
```

### Workflow 3: Trade Execution

Create file: `workflows/trade_execution.yaml`

```yaml
# Trade Execution Workflow
# Schema: A2rchitech Workflow Definition Schema v1.0
# Trigger: Manual approval or automated signal

version: "1.0"

workflow:
  id: trade-execution-v1
  name: Trade Execution
  description: |
    Executes approved trades with full validation, risk checking,
    order management, and audit logging.
  version: "1.0.0"
  tenant_id: alpha-trader

  required_tiers:
    - T0
    - T1
    - T2
    - T3

  success_criteria: |
    Order filled within acceptable slippage, position verified, audit logged

  failure_modes:
    - order_rejected: Log reason, notify, do not retry
    - partial_fill: Evaluate and decide (complete or cancel remainder)
    - timeout: Cancel order, log, notify

  phases_used:
    - Plan
    - Execute
    - Verify

  nodes:
    - id: validate-trade
      name: Validate Trade Parameters
      phase: Plan
      skill_id: validate_trade
      description: |
        Validate all trade parameters:
        - Symbol exists and is tradeable
        - Price is within reasonable range
        - Size is within limits
        - Account has sufficient margin
      inputs:
        - trade_request
      outputs:
        - validated_trade
      tools:
        - validate_trade
      constraints:
        time_budget: 15

    - id: check-risk-limits
      name: Check Risk Limits
      phase: Plan
      skill_id: evaluate_portfolio_risk
      description: |
        Final risk check before execution:
        - Position size within limits
        - Daily loss limit not breached
        - Portfolio concentration acceptable
      inputs:
        - validated_trade
        - current_portfolio
      outputs:
        - risk_approved_trade
      tools:
        - evaluate_portfolio_risk
      constraints:
        time_budget: 15

    - id: submit-order
      name: Submit Order
      phase: Execute
      skill_id: submit_order
      description: |
        Submit order to broker:
        - Select order type (limit/market)
        - Set time in force
        - Submit via API
        - Track order ID
      inputs:
        - risk_approved_trade
      outputs:
        - order_submission_result
      tools:
        - submit_order
      constraints:
        time_budget: 30

    - id: monitor-fill
      name: Monitor Order Fill
      phase: Execute
      skill_id: get_order_status
      description: |
        Monitor order until filled or timeout:
        - Poll order status
        - Handle partial fills
        - Cancel if timeout reached
      inputs:
        - order_submission_result
      outputs:
        - fill_result
      tools:
        - get_order_status
        - modify_order
        - cancel_order
      constraints:
        time_budget: 300

    - id: verify-position
      name: Verify Position
      phase: Verify
      skill_id: get_positions
      description: |
        Verify position matches expected:
        - Query current positions
        - Compare to expected
        - Flag discrepancies
      inputs:
        - fill_result
      outputs:
        - position_verification
      tools:
        - get_positions
      constraints:
        time_budget: 15

    - id: analyze-execution
      name: Analyze Execution Quality
      phase: Verify
      skill_id: verify_fill_quality
      description: |
        Analyze execution quality:
        - Calculate slippage
        - Compare to expected cost
        - Score execution
      inputs:
        - fill_result
        - risk_approved_trade
      outputs:
        - execution_analysis
      tools:
        - verify_fill_quality
      constraints:
        time_budget: 15

    - id: log-execution
      name: Log Execution
      phase: Verify
      skill_id: log_execution
      description: |
        Create immutable audit log entry:
        - Full trade details
        - Fill information
        - Execution analysis
        - Timestamp
      inputs:
        - fill_result
        - position_verification
        - execution_analysis
      outputs:
        - audit_log_entry
      tools:
        - log_execution
      constraints:
        time_budget: 15

  edges:
    - from: validate-trade
      to: check-risk-limits
    - from: check-risk-limits
      to: submit-order
      condition: "risk_approved == true"
    - from: submit-order
      to: monitor-fill
    - from: monitor-fill
      to: verify-position
    - from: monitor-fill
      to: analyze-execution
    - from: verify-position
      to: log-execution
    - from: analyze-execution
      to: log-execution
```

### Workflow 4: Continuous Monitoring

Create file: `workflows/continuous_monitoring.yaml`

```yaml
# Continuous Monitoring Workflow
# Schema: A2rchitech Workflow Definition Schema v1.0
# Schedule: Every 5 minutes during market hours (9:30 AM - 4:00 PM ET)

version: "1.0"

workflow:
  id: continuous-monitoring-v1
  name: Continuous Position Monitoring
  description: |
    Monitors open positions for stop conditions, price alerts,
    and risk limit breaches. Executes emergency actions when needed.
  version: "1.0.0"
  tenant_id: alpha-trader

  required_tiers:
    - T0
    - T1
    - T2
    - T3
    - T4

  success_criteria: |
    All positions checked, stops evaluated, alerts processed

  failure_modes:
    - position_query_failed: Retry immediately, alert if persists
    - stop_execution_failed: Emergency escalation

  phases_used:
    - Observe
    - Verify
    - Execute

  nodes:
    - id: fetch-positions
      name: Fetch Current Positions
      phase: Observe
      skill_id: get_positions
      description: Query all open positions from broker
      inputs: []
      outputs:
        - current_positions
      tools:
        - get_positions
      constraints:
        time_budget: 15

    - id: fetch-prices
      name: Fetch Current Prices
      phase: Observe
      skill_id: fetch_prices
      description: Get current market prices for all positions
      inputs:
        - current_positions
      outputs:
        - current_prices
      tools:
        - fetch_prices
      constraints:
        time_budget: 15

    - id: evaluate-stops
      name: Evaluate Stop Conditions
      phase: Verify
      skill_id: evaluate_stops
      description: |
        Check each position against stop conditions:
        - Hard stop loss
        - Trailing stop
        - Time-based stop
        - Profit target
      inputs:
        - current_positions
        - current_prices
      outputs:
        - stop_triggers
      tools:
        - evaluate_stops
      constraints:
        time_budget: 15

    - id: evaluate-alerts
      name: Evaluate Price Alerts
      phase: Verify
      skill_id: evaluate_alerts
      description: Check price alert conditions
      inputs:
        - current_prices
        - alert_config
      outputs:
        - triggered_alerts
      tools:
        - evaluate_alerts
      constraints:
        time_budget: 15

    - id: execute-stops
      name: Execute Stop Orders
      phase: Execute
      skill_id: emergency_close
      description: |
        Execute any triggered stops immediately.
        This is a T4 action - no confirmation required.
      inputs:
        - stop_triggers
      outputs:
        - stop_execution_results
      tools:
        - emergency_close
      constraints:
        time_budget: 60

    - id: send-alerts
      name: Send Alert Notifications
      phase: Execute
      skill_id: send_alert
      description: Notify of triggered alerts
      inputs:
        - triggered_alerts
      outputs:
        - alert_delivery_status
      tools:
        - send_alert
      constraints:
        time_budget: 30

    - id: log-monitoring
      name: Log Monitoring Cycle
      phase: Verify
      skill_id: log_execution
      description: Record monitoring results
      inputs:
        - stop_execution_results
        - alert_delivery_status
      outputs:
        - monitoring_log
      tools:
        - log_execution
      constraints:
        time_budget: 15

  edges:
    - from: fetch-positions
      to: fetch-prices
    - from: fetch-prices
      to: evaluate-stops
    - from: fetch-prices
      to: evaluate-alerts
    - from: evaluate-stops
      to: execute-stops
      condition: "stop_triggers.length > 0"
    - from: evaluate-alerts
      to: send-alerts
      condition: "triggered_alerts.length > 0"
    - from: execute-stops
      to: log-monitoring
    - from: send-alerts
      to: log-monitoring
```

---

## 5. Tool Registry (Full YAML)

Create file: `tools/tool_registry.yaml`

```yaml
# Alpha Trader Tool Registry
# Schema: A2rchitech Tool Definition Schema
# Maps tools to implementations and defines permissions

version: "1.0"
tenant_id: alpha-trader

tools:
  # ============================================================================
  # MARKET DATA TOOLS (T1-T2)
  # ============================================================================

  - id: fetch_options_chain
    name: Fetch Options Chain
    description: Fetch full options chain for a symbol
    tier: T2
    category: market_data
    provider: interactive_brokers
    rate_limit:
      requests_per_minute: 30
    parameters:
      - name: symbol
        type: string
        required: true
      - name: expiration_range_days
        type: integer
        default: 60
      - name: include_greeks
        type: boolean
        default: true
    returns:
      type: object
      schema:
        calls: array
        puts: array
        underlying_price: number
        timestamp: string
    implementation:
      standalone: tools/market_data.py::fetch_options_chain
      a2rchitech: capsules/market-data-v1.wasm::fetch_options_chain

  - id: fetch_futures_data
    name: Fetch Futures Data
    description: Fetch futures contract data
    tier: T2
    category: market_data
    provider: ninjatrader
    rate_limit:
      requests_per_minute: 60
    parameters:
      - name: contract
        type: string
        required: true
      - name: data_type
        type: string
        enum: [quote, ohlcv, depth]
        default: quote
    returns:
      type: object
    implementation:
      standalone: tools/market_data.py::fetch_futures_data

  - id: fetch_crypto_data
    name: Fetch Cryptocurrency Data
    description: Fetch crypto data via CCXT
    tier: T1
    category: market_data
    provider: ccxt
    rate_limit:
      requests_per_minute: 1200
    parameters:
      - name: exchange
        type: string
        required: true
      - name: symbol
        type: string
        required: true
      - name: timeframe
        type: string
        default: "1h"
    returns:
      type: object
    implementation:
      standalone: tools/market_data.py::fetch_crypto_data

  - id: fetch_polymarket
    name: Fetch Polymarket Data
    description: Fetch prediction market data from Polymarket
    tier: T1
    category: market_data
    provider: polymarket
    rate_limit:
      requests_per_minute: 100
    parameters:
      - name: market_id
        type: string
        required: false
      - name: active_only
        type: boolean
        default: true
    returns:
      type: array
    implementation:
      standalone: tools/market_data.py::fetch_polymarket

  - id: fetch_news
    name: Fetch News
    description: Fetch financial news headlines
    tier: T1
    category: market_data
    provider: newsapi
    rate_limit:
      requests_per_day: 100
    parameters:
      - name: symbols
        type: array
        required: false
      - name: hours_back
        type: integer
        default: 24
    returns:
      type: array
    implementation:
      standalone: tools/market_data.py::fetch_news

  # ============================================================================
  # ANALYSIS TOOLS (T0-T1)
  # ============================================================================

  - id: calculate_technicals
    name: Calculate Technical Indicators
    description: Calculate technical analysis indicators
    tier: T0
    category: analysis
    provider: local
    stateless: true
    parameters:
      - name: ohlcv_data
        type: array
        required: true
      - name: indicators
        type: array
        default: ["sma_20", "sma_50", "rsi_14", "macd"]
    returns:
      type: object
    implementation:
      standalone: tools/analysis.py::calculate_technicals

  - id: analyze_options_greeks
    name: Analyze Options Greeks
    description: Calculate and analyze options Greeks
    tier: T0
    category: analysis
    provider: local
    stateless: true
    parameters:
      - name: options_chain
        type: object
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/analysis.py::analyze_options_greeks

  - id: evaluate_sentiment
    name: Evaluate Sentiment
    description: Score sentiment from text data
    tier: T1
    category: analysis
    provider: llm
    parameters:
      - name: texts
        type: array
        required: true
    returns:
      type: object
      schema:
        overall_score: number
        breakdown: object
    implementation:
      standalone: tools/analysis.py::evaluate_sentiment

  - id: detect_patterns
    name: Detect Chart Patterns
    description: Detect technical chart patterns
    tier: T0
    category: analysis
    provider: local
    stateless: true
    parameters:
      - name: ohlcv_data
        type: array
        required: true
    returns:
      type: array
    implementation:
      standalone: tools/analysis.py::detect_patterns

  # ============================================================================
  # STRATEGY TOOLS (T1-T2)
  # ============================================================================

  - id: generate_trade_idea
    name: Generate Trade Idea
    description: Generate a trade recommendation from signals
    tier: T1
    category: strategy
    provider: llm
    parameters:
      - name: signals
        type: object
        required: true
      - name: risk_params
        type: object
        required: true
    returns:
      type: object
      schema:
        symbol: string
        direction: string
        entry_price: number
        stop_loss: number
        take_profit: number
        conviction: number
    implementation:
      standalone: tools/strategy.py::generate_trade_idea

  - id: calculate_position_size
    name: Calculate Position Size
    description: Calculate optimal position size
    tier: T0
    category: strategy
    provider: local
    stateless: true
    parameters:
      - name: account_value
        type: number
        required: true
      - name: risk_per_trade_pct
        type: number
        default: 1.0
      - name: stop_distance
        type: number
        required: true
    returns:
      type: object
      schema:
        shares: integer
        dollar_value: number
        risk_amount: number
    implementation:
      standalone: tools/strategy.py::calculate_position_size

  - id: evaluate_portfolio_risk
    name: Evaluate Portfolio Risk
    description: Calculate portfolio-level risk metrics
    tier: T1
    category: strategy
    provider: local
    parameters:
      - name: positions
        type: array
        required: true
      - name: proposed_trade
        type: object
        required: false
    returns:
      type: object
      schema:
        total_exposure: number
        var_95: number
        max_drawdown: number
        concentration_risk: object
    implementation:
      standalone: tools/strategy.py::evaluate_portfolio_risk

  # ============================================================================
  # EXECUTION TOOLS (T3-T4)
  # ============================================================================

  - id: submit_order
    name: Submit Order
    description: Submit an order to the broker
    tier: T3
    category: execution
    provider: interactive_brokers
    requires_confirmation: true
    parameters:
      - name: symbol
        type: string
        required: true
      - name: side
        type: string
        enum: [buy, sell]
        required: true
      - name: quantity
        type: integer
        required: true
      - name: order_type
        type: string
        enum: [market, limit, stop, stop_limit]
        default: limit
      - name: limit_price
        type: number
        required: false
      - name: stop_price
        type: number
        required: false
      - name: time_in_force
        type: string
        enum: [day, gtc, ioc, fok]
        default: day
    returns:
      type: object
      schema:
        order_id: string
        status: string
        submitted_at: string
    implementation:
      standalone: tools/execution.py::submit_order

  - id: modify_order
    name: Modify Order
    description: Modify an existing order
    tier: T3
    category: execution
    provider: interactive_brokers
    parameters:
      - name: order_id
        type: string
        required: true
      - name: new_quantity
        type: integer
        required: false
      - name: new_limit_price
        type: number
        required: false
    returns:
      type: object
    implementation:
      standalone: tools/execution.py::modify_order

  - id: cancel_order
    name: Cancel Order
    description: Cancel an existing order
    tier: T3
    category: execution
    provider: interactive_brokers
    parameters:
      - name: order_id
        type: string
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/execution.py::cancel_order

  - id: emergency_close
    name: Emergency Position Close
    description: Immediately close a position (T4 - no confirmation)
    tier: T4
    category: execution
    provider: interactive_brokers
    requires_confirmation: false
    circuit_breaker: true
    parameters:
      - name: symbol
        type: string
        required: true
      - name: reason
        type: string
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/execution.py::emergency_close

  - id: get_positions
    name: Get Positions
    description: Query current positions
    tier: T2
    category: execution
    provider: interactive_brokers
    parameters: []
    returns:
      type: array
    implementation:
      standalone: tools/execution.py::get_positions

  - id: get_order_status
    name: Get Order Status
    description: Query order status
    tier: T2
    category: execution
    provider: interactive_brokers
    parameters:
      - name: order_id
        type: string
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/execution.py::get_order_status

  # ============================================================================
  # REPORTING TOOLS (T0-T1)
  # ============================================================================

  - id: generate_report
    name: Generate Report
    description: Generate formatted report
    tier: T0
    category: reporting
    provider: local
    parameters:
      - name: report_data
        type: object
        required: true
      - name: format
        type: string
        enum: [text, html, markdown]
        default: markdown
    returns:
      type: string
    implementation:
      standalone: tools/reporting.py::generate_report

  - id: log_execution
    name: Log Execution
    description: Write to immutable audit log
    tier: T0
    category: reporting
    provider: local
    parameters:
      - name: action
        type: string
        required: true
      - name: details
        type: object
        required: true
    returns:
      type: object
      schema:
        log_id: string
        timestamp: string
    implementation:
      standalone: tools/reporting.py::log_execution

  - id: calculate_pnl
    name: Calculate P&L
    description: Calculate profit/loss for positions
    tier: T0
    category: reporting
    provider: local
    stateless: true
    parameters:
      - name: positions
        type: array
        required: true
      - name: current_prices
        type: object
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/reporting.py::calculate_pnl

  # ============================================================================
  # DELIVERY TOOLS (T1)
  # ============================================================================

  - id: send_email
    name: Send Email
    description: Send email notification
    tier: T1
    category: delivery
    provider: smtp
    rate_limit:
      requests_per_hour: 50
    parameters:
      - name: to
        type: string
        required: true
      - name: subject
        type: string
        required: true
      - name: body
        type: string
        required: true
      - name: html
        type: boolean
        default: false
    returns:
      type: object
    implementation:
      standalone: tools/delivery.py::send_email

  - id: send_sms
    name: Send SMS
    description: Send SMS notification
    tier: T1
    category: delivery
    provider: twilio
    rate_limit:
      requests_per_minute: 10
    parameters:
      - name: to
        type: string
        required: true
      - name: message
        type: string
        required: true
    returns:
      type: object
    implementation:
      standalone: tools/delivery.py::send_sms

  - id: send_alert
    name: Send Alert
    description: Send urgent alert via all channels
    tier: T1
    category: delivery
    provider: multi
    parameters:
      - name: message
        type: string
        required: true
      - name: severity
        type: string
        enum: [info, warning, critical]
        default: warning
    returns:
      type: object
    implementation:
      standalone: tools/delivery.py::send_alert
```

---

## 6. Standalone Implementation Plan

### Directory Structure

```
alpha-trader/
├── ALPHA_TRADER_HANDOFF.md          # This document
├── agent_templates.yaml              # Agent definitions (copy from Section 3)
├── workflows/
│   ├── daily_research_cycle.yaml    # Copy from Section 4
│   ├── morning_report.yaml          # Copy from Section 4
│   ├── trade_execution.yaml         # Copy from Section 4
│   └── continuous_monitoring.yaml   # Copy from Section 4
├── tools/
│   ├── tool_registry.yaml           # Copy from Section 5
│   ├── market_data.py               # Market data implementations
│   ├── analysis.py                  # Analysis implementations
│   ├── strategy.py                  # Strategy implementations
│   ├── execution.py                 # Order execution implementations
│   ├── reporting.py                 # Reporting implementations
│   └── delivery.py                  # Notification implementations
├── standalone/
│   ├── main.py                      # Entry point
│   ├── scheduler.py                 # APScheduler setup
│   ├── orchestrator.py              # Workflow orchestrator
│   ├── config.py                    # Configuration loader
│   ├── models.py                    # Data models
│   └── requirements.txt             # Dependencies
├── config/
│   ├── config.yaml                  # Main configuration
│   ├── watchlists.yaml              # Symbol watchlists
│   └── secrets.env                  # API keys (gitignored)
└── data/
    ├── research/                    # Research cache (SQLite)
    ├── reports/                     # Generated reports
    ├── audit/                       # Audit logs
    └── positions/                   # Position tracking
```

### Core Python Files

#### standalone/main.py

```python
#!/usr/bin/env python3
"""
Alpha Trader - Main Entry Point

Usage:
    python main.py                    # Start scheduler
    python main.py --workflow NAME    # Run specific workflow
    python main.py --test             # Run in test mode
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from config import Config
from scheduler import Scheduler
from orchestrator import WorkflowOrchestrator

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('alpha-trader')


class AlphaTrader:
    """Main Alpha Trader application."""

    def __init__(self, config_path: str = 'config/config.yaml'):
        self.config = Config.load(config_path)
        self.orchestrator = WorkflowOrchestrator(self.config)
        self.scheduler = Scheduler(self.orchestrator, self.config)
        self.running = False

    async def start(self):
        """Start the Alpha Trader system."""
        logger.info("Starting Alpha Trader...")
        self.running = True

        # Initialize components
        await self.orchestrator.initialize()

        # Start scheduler
        self.scheduler.start()

        logger.info("Alpha Trader started successfully")

        # Keep running until stopped
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """Stop the Alpha Trader system."""
        logger.info("Stopping Alpha Trader...")
        self.running = False
        self.scheduler.stop()
        await self.orchestrator.shutdown()
        logger.info("Alpha Trader stopped")

    async def run_workflow(self, workflow_name: str):
        """Run a specific workflow."""
        logger.info(f"Running workflow: {workflow_name}")
        result = await self.orchestrator.execute_workflow(workflow_name)
        logger.info(f"Workflow {workflow_name} completed: {result}")
        return result


async def main():
    parser = argparse.ArgumentParser(description='Alpha Trader')
    parser.add_argument('--config', default='config/config.yaml',
                        help='Path to config file')
    parser.add_argument('--workflow', help='Run specific workflow')
    parser.add_argument('--test', action='store_true', help='Test mode')
    args = parser.parse_args()

    trader = AlphaTrader(args.config)

    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(trader.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if args.workflow:
        # Run single workflow
        await trader.run_workflow(args.workflow)
    else:
        # Start full system
        await trader.start()


if __name__ == '__main__':
    asyncio.run(main())
```

#### standalone/scheduler.py

```python
"""
Scheduler - APScheduler-based workflow scheduling

Schedules:
- 04:00 ET: daily-research-cycle
- 06:00 ET: morning-report
- Every 5 min: continuous-monitoring (market hours only)
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz

ET = pytz.timezone('America/New_York')


class Scheduler:
    """Workflow scheduler using APScheduler."""

    def __init__(self, orchestrator, config):
        self.orchestrator = orchestrator
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._setup_jobs()

    def _setup_jobs(self):
        """Configure scheduled jobs."""

        # Daily Research Cycle - 4:00 AM ET
        self.scheduler.add_job(
            self._run_daily_research,
            CronTrigger(hour=4, minute=0, timezone=ET),
            id='daily-research-cycle',
            name='Daily Research Cycle',
            misfire_grace_time=300
        )

        # Morning Report - 6:00 AM ET
        self.scheduler.add_job(
            self._run_morning_report,
            CronTrigger(hour=6, minute=0, timezone=ET),
            id='morning-report',
            name='Morning Report',
            misfire_grace_time=300
        )

        # Continuous Monitoring - Every 5 minutes during market hours
        self.scheduler.add_job(
            self._run_monitoring,
            CronTrigger(
                day_of_week='mon-fri',
                hour='9-16',
                minute='*/5',
                timezone=ET
            ),
            id='continuous-monitoring',
            name='Continuous Monitoring',
            misfire_grace_time=60
        )

    async def _run_daily_research(self):
        """Execute daily research cycle."""
        await self.orchestrator.execute_workflow('daily-research-cycle-v1')

    async def _run_morning_report(self):
        """Execute morning report generation."""
        await self.orchestrator.execute_workflow('morning-report-v1')

    async def _run_monitoring(self):
        """Execute continuous monitoring."""
        await self.orchestrator.execute_workflow('continuous-monitoring-v1')

    def start(self):
        """Start the scheduler."""
        self.scheduler.start()

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
```

#### standalone/orchestrator.py

```python
"""
Workflow Orchestrator - Executes workflow DAGs

Implements A2rchitech scientific loop phases:
OBSERVE → THINK → PLAN → BUILD → EXECUTE → VERIFY → LEARN
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List
import yaml

from models import WorkflowNode, WorkflowResult, ExecutionContext

logger = logging.getLogger('orchestrator')


class WorkflowOrchestrator:
    """Executes workflows defined in YAML."""

    def __init__(self, config):
        self.config = config
        self.workflows = {}
        self.tools = {}
        self.context = ExecutionContext()

    async def initialize(self):
        """Load workflows and tools."""
        # Load workflows
        workflows_dir = Path('workflows')
        for wf_file in workflows_dir.glob('*.yaml'):
            wf_data = yaml.safe_load(wf_file.read_text())
            wf = wf_data['workflow']
            self.workflows[wf['id']] = wf
            logger.info(f"Loaded workflow: {wf['id']}")

        # Load tools
        tools_file = Path('tools/tool_registry.yaml')
        tools_data = yaml.safe_load(tools_file.read_text())
        for tool in tools_data['tools']:
            self.tools[tool['id']] = tool
            logger.info(f"Loaded tool: {tool['id']}")

    async def execute_workflow(self, workflow_id: str) -> WorkflowResult:
        """Execute a workflow by ID."""
        if workflow_id not in self.workflows:
            raise ValueError(f"Unknown workflow: {workflow_id}")

        workflow = self.workflows[workflow_id]
        logger.info(f"Starting workflow: {workflow['name']}")

        start_time = datetime.utcnow()
        results = {}

        try:
            # Build DAG and execute
            execution_order = self._topological_sort(workflow)

            for node_id in execution_order:
                node = self._get_node(workflow, node_id)
                logger.info(f"Executing node: {node['name']} (phase: {node['phase']})")

                # Gather inputs from previous nodes
                inputs = self._gather_inputs(node, results)

                # Execute node
                node_result = await self._execute_node(node, inputs)
                results[node_id] = node_result

                # Store outputs
                for output in node.get('outputs', []):
                    self.context.set(output, node_result.get(output))

            return WorkflowResult(
                workflow_id=workflow_id,
                status='success',
                start_time=start_time,
                end_time=datetime.utcnow(),
                results=results
            )

        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed: {e}")
            return WorkflowResult(
                workflow_id=workflow_id,
                status='failed',
                start_time=start_time,
                end_time=datetime.utcnow(),
                error=str(e)
            )

    def _topological_sort(self, workflow: dict) -> List[str]:
        """Sort nodes in execution order respecting dependencies."""
        nodes = {n['id']: n for n in workflow['nodes']}
        edges = workflow.get('edges', [])

        # Build adjacency list
        in_degree = {n: 0 for n in nodes}
        graph = {n: [] for n in nodes}

        for edge in edges:
            graph[edge['from']].append(edge['to'])
            in_degree[edge['to']] += 1

        # Kahn's algorithm
        queue = [n for n in nodes if in_degree[n] == 0]
        result = []

        while queue:
            node = queue.pop(0)
            result.append(node)

            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def _get_node(self, workflow: dict, node_id: str) -> dict:
        """Get node by ID."""
        for node in workflow['nodes']:
            if node['id'] == node_id:
                return node
        raise ValueError(f"Node not found: {node_id}")

    def _gather_inputs(self, node: dict, results: dict) -> dict:
        """Gather inputs from previous node outputs."""
        inputs = {}
        for input_name in node.get('inputs', []):
            if input_name in self.context.data:
                inputs[input_name] = self.context.get(input_name)
        return inputs

    async def _execute_node(self, node: dict, inputs: dict) -> dict:
        """Execute a single workflow node."""
        tool_id = node.get('skill_id')

        if tool_id and tool_id in self.tools:
            tool = self.tools[tool_id]
            # Import and execute tool implementation
            impl_path = tool['implementation']['standalone']
            module_path, func_name = impl_path.rsplit('::', 1)

            # Dynamic import
            import importlib
            module = importlib.import_module(module_path.replace('/', '.').replace('.py', ''))
            func = getattr(module, func_name)

            # Execute
            result = await func(**inputs) if asyncio.iscoroutinefunction(func) else func(**inputs)
            return result

        return {}

    async def shutdown(self):
        """Clean shutdown."""
        logger.info("Orchestrator shutting down")
```

#### standalone/requirements.txt

```
# Alpha Trader Dependencies

# Core
python>=3.10
pyyaml>=6.0
pydantic>=2.0

# Async
asyncio
aiohttp>=3.8

# Scheduling
apscheduler>=3.10

# Database
sqlite3
aiosqlite>=0.19

# Market Data
ccxt>=4.0           # Crypto (108 exchanges)
yfinance>=0.2       # Stock data fallback
polygon-api-client  # Options data (if using Polygon)

# Analysis
pandas>=2.0
numpy>=1.24
ta-lib              # Technical analysis
scipy               # Statistical functions

# ML/LLM
openai>=1.0         # GPT-4 API
anthropic>=0.8      # Claude API

# Broker APIs
ib_insync>=0.9      # Interactive Brokers
schwab-api          # Charles Schwab (if available)

# Notifications
twilio>=8.0         # SMS
sendgrid>=6.0       # Email

# Utilities
python-dotenv>=1.0  # Environment variables
pytz>=2023.3        # Timezone handling
loguru>=0.7         # Better logging
```

---

## 7. API Integration Details

### Interactive Brokers (IB) Setup

```python
# tools/execution.py - IB Integration

from ib_insync import IB, Stock, Option, MarketOrder, LimitOrder

class IBClient:
    """Interactive Brokers API client."""

    def __init__(self, host='127.0.0.1', port=7497, client_id=1):
        self.ib = IB()
        self.host = host
        self.port = port
        self.client_id = client_id

    async def connect(self):
        """Connect to IB Gateway/TWS."""
        await self.ib.connectAsync(self.host, self.port, self.client_id)

    async def submit_order(self, symbol: str, side: str, quantity: int,
                          order_type: str = 'limit', limit_price: float = None):
        """Submit order to IB."""
        contract = Stock(symbol, 'SMART', 'USD')
        await self.ib.qualifyContractsAsync(contract)

        if order_type == 'market':
            order = MarketOrder(side.upper(), quantity)
        else:
            order = LimitOrder(side.upper(), quantity, limit_price)

        trade = self.ib.placeOrder(contract, order)
        return {
            'order_id': trade.order.orderId,
            'status': trade.orderStatus.status,
            'submitted_at': datetime.utcnow().isoformat()
        }

    async def get_positions(self):
        """Get current positions."""
        positions = self.ib.positions()
        return [
            {
                'symbol': p.contract.symbol,
                'quantity': p.position,
                'avg_cost': p.avgCost,
                'market_value': p.marketValue
            }
            for p in positions
        ]
```

### CCXT Crypto Integration

```python
# tools/market_data.py - CCXT Integration

import ccxt.async_support as ccxt

class CryptoClient:
    """Crypto exchange client via CCXT."""

    def __init__(self, exchange_id: str, api_key: str = None, secret: str = None):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({
            'apiKey': api_key,
            'secret': secret,
            'enableRateLimit': True
        })

    async def fetch_crypto_data(self, symbol: str, timeframe: str = '1h', limit: int = 100):
        """Fetch OHLCV data."""
        ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'data': [
                {
                    'timestamp': candle[0],
                    'open': candle[1],
                    'high': candle[2],
                    'low': candle[3],
                    'close': candle[4],
                    'volume': candle[5]
                }
                for candle in ohlcv
            ]
        }

    async def close(self):
        await self.exchange.close()
```

### Polymarket Integration

```python
# tools/market_data.py - Polymarket Integration

import aiohttp

class PolymarketClient:
    """Polymarket prediction market client."""

    BASE_URL = "https://clob.polymarket.com"

    async def fetch_polymarket(self, market_id: str = None, active_only: bool = True):
        """Fetch prediction market data."""
        async with aiohttp.ClientSession() as session:
            if market_id:
                url = f"{self.BASE_URL}/markets/{market_id}"
            else:
                url = f"{self.BASE_URL}/markets"
                if active_only:
                    url += "?active=true"

            async with session.get(url) as resp:
                data = await resp.json()
                return data
```

---

## 8. Step-by-Step Build Instructions

### Phase 1: Setup (Day 1)

```bash
# 1. Create directory structure
cd "/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader"
mkdir -p workflows tools standalone config data/{research,reports,audit,positions}

# 2. Copy YAML files from this document
# - agent_templates.yaml (Section 3)
# - workflows/*.yaml (Section 4)
# - tools/tool_registry.yaml (Section 5)

# 3. Create Python environment
cd standalone
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Create config files
cp config/config.example.yaml config/config.yaml
# Edit with your API keys
```

### Phase 2: Implement Tools (Days 2-3)

```bash
# Implement in order:
# 1. tools/market_data.py - Start with crypto (easiest)
# 2. tools/analysis.py - Technical indicators
# 3. tools/strategy.py - Position sizing
# 4. tools/reporting.py - Report generation
# 5. tools/execution.py - Order execution (paper trading first)
# 6. tools/delivery.py - Notifications
```

### Phase 3: Test Workflows (Day 4)

```bash
# Test individual workflows
python main.py --workflow daily-research-cycle-v1
python main.py --workflow morning-report-v1

# Check outputs
ls -la data/research/
ls -la data/reports/
```

### Phase 4: Production (Day 5)

```bash
# Start full system
python main.py

# Monitor logs
tail -f logs/alpha-trader.log

# Check scheduler status
# (APScheduler logs next run times)
```

---

## 9. A2rchitech Migration Path

### Current State (Standalone)

```
[Python Scheduler] → [Python Orchestrator] → [Python Tools]
         ↓                    ↓                    ↓
    APScheduler        Custom DAG          Direct API calls
```

### Target State (A2rchitech)

```
[A2rchitech Scheduler] → [A2rchitech Workflow Engine] → [WASM Capsules]
         ↓                         ↓                         ↓
   Workflow triggers        Kernel contracts          Signed tools
```

### Migration Steps

1. **Phase 1: Register Tools**
   - Package Python tools as WASM capsules
   - Sign with A2rchitech capsule system
   - Register in A2rchitech registry

2. **Phase 2: Port Workflows**
   - YAML files already match schema (zero changes)
   - Import into A2rchitech workflow engine
   - Test execution

3. **Phase 3: Connect Gateways**
   - Route reports through gateway-imessage
   - Add gateway-sms for alerts
   - Enable web dashboard

4. **Phase 4: Full Integration**
   - Use A2rchitech scheduler
   - Full policy engine integration
   - Multi-tenant support

### Zero-Drift Guarantee

| Component | Standalone | A2rchitech | Drift |
|-----------|------------|------------|-------|
| Agent Templates | YAML | YAML | None |
| Workflows | YAML | YAML | None |
| Tool Registry | YAML | YAML | None |
| Audit Format | JSON | JSON | None |
| Phases | Scientific Loop | Scientific Loop | None |
| Tiers | T0-T4 | T0-T4 | None |

---

## Summary

This handoff provides everything needed to build the Alpha Trader system:

1. **Architecture** - Complete system design with agent roles
2. **Agent Templates** - Full YAML matching A2rchitech schema
3. **Workflows** - Four complete workflow definitions
4. **Tool Registry** - 25+ tools with full specifications
5. **Implementation** - Python code for standalone operation
6. **API Details** - Integration code for IB, CCXT, Polymarket
7. **Build Instructions** - Step-by-step setup guide
8. **Migration Path** - Clear path to A2rchitech integration

**Next Session Action:** Copy the YAML files from Sections 3-5 into the appropriate locations, then implement the Python tools starting with `market_data.py`.

---

*End of Handoff - Alpha Trader Agent System*
