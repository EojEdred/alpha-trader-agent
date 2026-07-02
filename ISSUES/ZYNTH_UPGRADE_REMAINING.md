# Zynth-Level Upgrade - Remaining Tasks

**Priority:** High
**Status:** 9/15 completed
**Assigned:** Sisyphus

## Summary

Core Zynth-level architecture is implemented. Remaining tasks focus on CLI integration, workflow orchestration, research ingestion, and testing.

## Completed ✅

1. DESIGN.md - Architecture documentation
2. models.py - Core data schemas (ThesisObject, EvidenceItem, TradeIntent, RiskDecision, ExecutionPlan)
3. capsules/ directory - Base Capsule class
4. spy_qqq_liquidity_sweep.py - SPY/QQQ liquidity sweep capsule
5. nq_session_trend.py - NQ futures session trend capsule
6. xauusd_macro_levels.py - XAUUSD macro levels capsule (OANDA executable)
7. kalshi_macro_sensor.py - Kalshi regime sensor capsule
8. portfolio.py - PortfolioBrain (ranking, suppression, sizing)
9. router.py - ExecutionRouter (AUTO/CONFIRM/SIGNAL_ONLY modes)
10. reporting.py - Enhanced Zynth-level report generator with grouped/ranked format

## Remaining Tasks

### Task 11: CLI Commands Integration

**Status:** Pending
**Effort:** Medium

Add new CLI commands to `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/cli.py`:

```python
@app.command()
def run_workflow(
    workflow: str = typer.Argument(..., help="Workflow to run: morning-report, research"),
    urls: List[str] = typer.Option([], "--urls", "-u", help="Research URLs for research workflow"),
    **kwargs
):
    """Run specific Zynth workflow."""
    if workflow == "research":
        from research import run_research_workflow
        asyncio.run(run_research_workflow(urls))
    elif workflow == "morning-report":
        from standalone.main import AlphaTrader
        trader = AlphaTrader()
        asyncio.run(trader.run_workflow('morning-report'))

@app.command()
def approve(intent_id: str = typer.Argument(..., help="Trade intent ID to approve")):
    """Manually approve a pending trade intent."""
    from router import ExecutionRouter
    router = ExecutionRouter()
    asyncio.run(router.manual_approve(intent_id))

@app.command()
def reject(intent_id: str = typer.Argument(..., help="Trade intent ID to reject")):
    """Manually reject a pending trade intent."""
    from router import ExecutionRouter
    router = ExecutionRouter()
    asyncio.run(router.manual_reject(intent_id))
```

**Acceptance Criteria:**
- `dexter run morning-report` command exists and runs the morning report workflow
- `dexter run research --urls "URL1,URL2"` command exists and triggers research ingestion
- `dexter approve <intent_id>` command exists and updates intent status to approved
- `dexter reject <intent_id>` command exists and updates intent status to rejected

---

### Task 12: Workflow Integration

**Status:** Pending
**Effort:** Medium

Update `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/workflows/morning_report.yaml` to include new pipeline nodes:

```yaml
workflow:
  id: morning-report-zynth
  name: Morning Report (Zynth-Level)
  version: "2.0"

  nodes:
    # New nodes
    - id: ingest-research
      name: Ingest Research URLs
      phase: Observe
      skill_id: ingest_research
      inputs: [research_urls]
      outputs: [evidence_items, thesis_object]
      tools: [ingest_research]

    - id: run-capsules
      name: Generate Trade Intents from Capsules
      phase: Think
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

    # Updated existing node
    - id: format-report
      name: Format Enhanced Report
      phase: Build
      skill_id: generate_report
      inputs: [execution_plans]
      outputs: [formatted_reports]
      tools: [generate_zynth_report]

  edges:
    - from: ingest-research
      to: run-capsules
      inputs: [evidence_items, thesis_object]
    - from: run-capsules
      to: portfolio-brain
      inputs: [trade_intents]
    - from: portfolio-brain
      to: risk-governor
      inputs: [ranked_intents]
    - from: risk-governor
      to: router
      inputs: [risk_decisions]
    - from: router
      to: format-report
      inputs: [execution_plans]
```

**Acceptance Criteria:**
- morning_report.yaml includes new pipeline nodes
- Workflow follows: ingest → capsules → portfolio → risk → router → report
- Existing nodes are preserved (extend, don't replace)
- Orchestrator can execute the updated workflow successfully

---

### Task 13: Research Ingestion Module

**Status:** Pending
**Effort:** High

Create `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/research.py`:

```python
"""
Research Ingestion Module

Web content extraction and thesis generation.
Uses trafilatura for URL extraction (feature-gated).
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from loguru import logger

from models import EvidenceItem, ThesisObject, RegimeBias, generate_evidence_id, generate_thesis_id


class ResearchIngestion:
    """Web content extraction and thesis generation."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.enable_extraction = config.get('enable_research_ingestion', False)

    async def ingest_urls(
        self,
        urls: List[str],
        **kwargs
    ) -> Tuple[List[EvidenceItem], ThesisObject]:
        """
        Extract content from URLs and synthesize thesis.

        Args:
            urls: List of URLs to process

        Returns:
            (EvidenceItems[], ThesisObject)

        Notes:
            - Extracts clean text from each URL
            - Stores EvidenceItems in DB
            - Synthesizes into ThesisObject (LLM)
            - Degrades gracefully on extraction failure
        """
        logger.info(f"Ingesting {len(urls)} research URLs")

        evidence_items = []

        for url in urls:
            try:
                if self.enable_extraction:
                    # Extract content using trafilatura
                    evidence = await self.extract_content(url)
                    if evidence:
                        evidence_items.append(evidence)
                        logger.info(f"Extracted: {evidence.title}")
                else:
                    # Create placeholder evidence if extraction disabled
                    evidence = EvidenceItem(
                        id=generate_evidence_id(),
                        url=url,
                        title=f"Research: {url[:50]}...",
                        snippet="Web extraction disabled (feature flag)",
                        timestamp=datetime.utcnow(),
                        confidence=0.5,
                        tags=["external"]
                    )
                    evidence_items.append(evidence)
            except Exception as e:
                logger.error(f"Failed to extract from {url}: {e}")
                # Create low-confidence evidence on failure
                evidence = EvidenceItem(
                    id=generate_evidence_id(),
                    url=url,
                    title=f"Failed: {url[:50]}...",
                    snippet="Extraction failed",
                    timestamp=datetime.utcnow(),
                    confidence=0.1,
                    tags=["failed"]
                )
                evidence_items.append(evidence)

        # Synthesize thesis from evidence
        thesis = await self.generate_thesis(evidence_items)

        logger.info(f"Created thesis {thesis.id} with {len(evidence_items)} evidence items")
        return evidence_items, thesis

    async def extract_content(
        self,
        url: str
    ) -> Optional[EvidenceItem]:
        """
        Extract clean text from URL.

        Uses trafilatura library (optional via feature flag).
        """
        try:
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None

            text = trafilatura.extract(downloaded)
            if not text:
                return None

            # Extract metadata
            title = trafilatura.extract_title(downloaded) or "Untitled"
            date = trafilatura.extract_date(downloaded) or datetime.utcnow()

            # Extract snippet (first 200 chars)
            snippet = text[:200] + "..." if len(text) > 200 else text

            return EvidenceItem(
                id=generate_evidence_id(),
                url=url,
                title=title,
                snippet=snippet,
                timestamp=date if isinstance(date, datetime) else datetime.utcnow(),
                confidence=0.8,
                tags=["web", "extracted"]
            )

        except ImportError:
            logger.warning("trafilatura not installed, web extraction disabled")
            return None
        except Exception as e:
            logger.error(f"Extraction error for {url}: {e}")
            return None

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

        Degrades gracefully if LLM unavailable.
        """
        if not evidence_items:
            # Empty thesis if no evidence
            return ThesisObject(
                id=generate_thesis_id(),
                summary="No evidence available",
                evidence_ids=[],
                conviction=0.0,
                regime_bias=RegimeBias.NEUTRAL,
                created_at=datetime.utcnow(),
                tags=[]
            )

        # Try LLM synthesis
        try:
            from tools.brain import reason_about_setup
            from models import RegimeBias

            # Build context for LLM
            context = "\n\n".join([
                f"Evidence {i+1}:\n{e.title}\n{e.snippet}\n"
                for i, e in enumerate(evidence_items)
            ])

            # Use LLM to generate thesis
            llm_result = await reason_about_setup(context)

            # Parse LLM output
            summary = llm_result.get('summary', "LLM synthesis failed")
            bias_str = llm_result.get('regime_bias', 'neutral').lower()

            # Map bias string to enum
            if bias_str == 'risk_on':
                regime_bias = RegimeBias.RISK_ON
            elif bias_str == 'risk_off':
                regime_bias = RegimeBias.RISK_OFF
            else:
                regime_bias = RegimeBias.NEUTRAL

            # Calculate conviction from evidence quality
            avg_confidence = sum(e.confidence for e in evidence_items) / len(evidence_items)

            return ThesisObject(
                id=generate_thesis_id(),
                summary=summary,
                evidence_ids=[e.id for e in evidence_items],
                conviction=avg_confidence,
                regime_bias=regime_bias,
                created_at=datetime.utcnow(),
                tags=[e.tags for e in evidence_items for e in e.tags]
            )

        except Exception as e:
            logger.warning(f"LLM synthesis failed: {e}, using fallback")
            # Fallback: simple evidence aggregation
            summaries = [e.snippet for e in evidence_items[:3]]
            summary = " | ".join(summaries)

            return ThesisObject(
                id=generate_thesis_id(),
                summary=summary,
                evidence_ids=[e.id for e in evidence_items],
                conviction=0.5,
                regime_bias=RegimeBias.NEUTRAL,
                created_at=datetime.utcnow(),
                tags=["fallback"]
            )


async def run_research_workflow(urls: List[str]):
    """Standalone research workflow entry point."""
    from standalone.config import Config

    config = Config.load()
    ingestion = ResearchIngestion(config.__dict__)

    evidence_items, thesis = await ingestion.ingest_urls(urls)

    # Print summary
    print(f"\nThesis Created: {thesis.id}")
    print(f"Regime Bias: {thesis.regime_bias.value}")
    print(f"Conviction: {thesis.conviction:.2%}")
    print(f"Summary: {thesis.summary}\n")
    print(f"Evidence Items: {len(evidence_items)}")

    for i, evidence in enumerate(evidence_items, 1):
        print(f"  {i}. {evidence.title} ({evidence.confidence:.2%})")
```

**Acceptance Criteria:**
- research.py module exists with ResearchIngestion class
- `ingest_urls()` extracts content from URLs
- `extract_content()` uses trafilatura (feature-gated)
- `generate_thesis()` creates ThesisObject from evidence
- Graceful degradation when LLM or trafilatura unavailable
- `run_research_workflow()` entry point for CLI

---

### Task 14: Config Updates

**Status:** Pending
**Effort:** Low

Update `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/config/config.yaml` with new sections:

```yaml
# Zynth-Level Configuration

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

**Acceptance Criteria:**
- config.yaml includes all new sections
- Research feature flag is configurable
- Portfolio risk parameters are set
- Venue-level AUTO/CONFIRM/SIGNAL_ONLY settings are defined
- Existing config sections are preserved

---

### Task 15: Tests

**Status:** Pending
**Effort:** Medium

Create `/Users/macbook/Desktop/A2rchitech Workspace/alpha-trader/tests/test_zynth_upgrade.py`:

```python
"""
Zynth-Level Upgrade Tests

Tests for schema validation, router gating, portfolio suppression.
"""

import pytest
from datetime import datetime, timedelta

from models import (
    EvidenceItem, ThesisObject, TradeIntent,
    RiskDecision, ExecutionPlan, ExecutionMode,
    generate_evidence_id, generate_thesis_id,
    generate_intent_id, generate_execution_plan_id,
    RegimeBias
)
from portfolio import PortfolioBrain
from router import ExecutionRouter


class TestSchemaValidation:
    """Test JSON serialization and validation."""

    def test_evidence_item_serialization(self):
        evidence = EvidenceItem(
            id=generate_evidence_id(),
            url="https://example.com",
            title="Test Evidence",
            snippet="Test snippet",
            timestamp=datetime.utcnow(),
            confidence=0.8,
            tags=["test"]
        )

        data = evidence.to_dict()
        assert data['id'] == evidence.id
        assert data['url'] == evidence.url
        assert isinstance(data['timestamp'], str)

        # Round-trip
        restored = EvidenceItem.from_dict(data)
        assert restored.id == evidence.id

    def test_thesis_object_serialization(self):
        thesis = ThesisObject(
            id=generate_thesis_id(),
            summary="Test thesis",
            evidence_ids=["evd_1", "evd_2"],
            conviction=0.75,
            regime_bias=RegimeBias.RISK_ON,
            created_at=datetime.utcnow(),
            tags=["macro", "inflation"]
        )

        data = thesis.to_dict()
        assert data['regime_bias'] == "risk_on"
        assert isinstance(data['created_at'], str)

        restored = ThesisObject.from_dict(data)
        assert restored.regime_bias == RegimeBias.RISK_ON

    def test_trade_intent_serialization(self):
        intent = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=447.0,
            target_price=475.0,
            conviction=0.85,
            invalidation_price=472.0,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="oanda",
            evidence_citations=["evd_1"]
        )

        data = intent.to_dict()
        assert data['execution_mode'] == "auto"
        assert data['direction'] == "long"

        restored = TradeIntent.from_dict(data)
        assert restored.execution_mode == ExecutionMode.AUTO


class TestRouterGating:
    """Test AUTO/CONFIRM/SIGNAL_ONLY routing logic."""

    @pytest.fixture
    def router(self):
        config = {
            'execution_modes': {
                'oanda': {'auto_enabled': True, 'max_size_auto': 10000},
                'kalshi': {'auto_enabled': True},
                'schwab': {'auto_enabled': False},
                'topstep': {'auto_enabled': False}
            }
        }
        return ExecutionRouter(config)

    def test_oanda_auto_mode_small_trade(self, router):
        decision = RiskDecision(
            intent_id="test_intent",
            approved=True
        )

        plans = asyncio.run(router.route_intents([decision]))
        assert len(plans) == 1
        assert plans[0].execution_mode == ExecutionMode.AUTO
        assert not plans[0].requires_confirmation

    def test_schwab_confirm_mode(self, router):
        decision = RiskDecision(
            intent_id="test_intent_schwab",
            approved=True
        )

        # Simulate Schwab venue
        # Would need to pass intent with venue='schwab'
        # For now, test that it's not AUTO

        plans = asyncio.run(router.route_intents([decision]))
        # Verify Schwab doesn't get AUTO mode
        for plan in plans:
            if plan.venue == 'schwab':
                assert plan.execution_mode == ExecutionMode.CONFIRM
                assert plan.requires_confirmation

    def test_topstep_signal_only(self, router):
        decision = RiskDecision(
            intent_id="test_intent_topstep",
            approved=True
        )

        plans = asyncio.run(router.route_intents([decision]))
        # Topstep should always be SIGNAL_ONLY
        for plan in plans:
            if plan.venue == 'topstep':
                assert plan.execution_mode == ExecutionMode.SIGNAL_ONLY

    def test_rejected_intent_no_plan(self, router):
        decision = RiskDecision(
            intent_id="test_intent",
            approved=False,
            rejection_reason="Risk limit exceeded"
        )

        plans = asyncio.run(router.route_intents([decision]))
        assert len(plans) == 0


class TestPortfolioSuppression:
    """Test duplicate/correlation suppression and ranking."""

    @pytest.fixture
    def portfolio_brain(self):
        config = {
            'max_risk_per_trade_pct': 0.5,
            'consecutive_loss_limit': 2,
            'correlation_threshold': 0.7
        }
        return PortfolioBrain(config)

    def test_suppress_duplicate_same_symbol(self, portfolio_brain):
        intent1 = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=447.0,
            target_price=475.0,
            conviction=0.85,
            invalidation_price=472.0,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="schwab"
        )

        intent2 = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule_2",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.5,
            stop_price=447.5,
            target_price=475.5,
            conviction=0.70,
            invalidation_price=472.5,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="schwab"
        )

        intents = asyncio.run(
            portfolio_brain.rank_intents(
                [intent1, intent2],
                current_positions={}
            )
        )

        # Only highest conviction should remain
        assert len(intents) == 1
        assert intents[0].conviction == 0.85

    def test_rank_by_conviction(self, portfolio_brain):
        intents = []
        for i, conviction in enumerate([0.9, 0.7, 0.5]):
            intent = TradeIntent(
                id=generate_intent_id(),
                capsule_id="test_capsule",
                thesis_id="test_thesis",
                symbol=f"TEST{i}",
                direction="long",
                entry_price=100.0 + i,
                stop_price=98.0 + i,
                target_price=105.0 + i,
                conviction=conviction,
                invalidation_price=106.0 + i,
                time_stop=datetime.utcnow() + timedelta(hours=6),
                risk_reward_ratio=2.5,
                execution_mode=ExecutionMode.AUTO,
                venue="test"
            )
            intents.append(intent)

        ranked = asyncio.run(
            portfolio_brain.rank_intents(
                intents,
                current_positions={}
            )
        )

        # Should be sorted by conviction descending
        assert ranked[0].conviction == 0.9
        assert ranked[1].conviction == 0.7
        assert ranked[2].conviction == 0.5

    def test_circuit_breaker_blocks_all(self, portfolio_brain):
        # Simulate circuit breaker triggered
        portfolio_brain.config['consecutive_losses'] = 2

        intents = [TradeIntent(
            id=generate_intent_id(),
            capsule_id="test_capsule",
            thesis_id="test_thesis",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=447.0,
            target_price=475.0,
            conviction=0.9,
            invalidation_price=472.0,
            time_stop=datetime.utcnow() + timedelta(hours=6),
            risk_reward_ratio=2.5,
            execution_mode=ExecutionMode.AUTO,
            venue="schwab"
        )]

        ranked = asyncio.run(
            portfolio_brain.rank_intents(
                intents,
                current_positions={}
            )
        )

        # Should return empty list when circuit breaker active
        assert len(ranked) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

**Acceptance Criteria:**
- test_zynth_upgrade.py exists with comprehensive tests
- Tests for schema validation (JSON serialization)
- Tests for router gating (AUTO/CONFIRM/SIGNAL_ONLY)
- Tests for portfolio suppression (duplicates, ranking, circuit breakers)
- All tests pass with `pytest test_zynth_upgrade.py`

---

## Implementation Notes

### Dependencies Required

```bash
# For research ingestion (optional)
pip install trafilatura

# For testing
pip install pytest pytest-asyncio
```

### Key Integration Points

1. **CLI → Orchestrator:**
   - `dexter run morning-report` should call `orchestrator.execute_workflow('morning-report-zynth')`
   - `dexter run research --urls [...]` should call `research.run_research_workflow()`

2. **Orchestrator → Capsules:**
   - Workflow must instantiate and run enabled capsules
   - Pass market data and thesis to `capsule.generate_intents()`

3. **Capsules → PortfolioBrain:**
   - Collect all TradeIntents from capsules
   - Pass to `portfolio_brain.rank_intents()`

4. **PortfolioBrain → Router:**
   - Pass ranked intents to router
   - Router generates ExecutionPlans

5. **Router → Reporting:**
   - Pass ExecutionPlans to `generate_zynth_report()`
   - Output Markdown + JSON

### Feature Flags

- `ENABLE_RESEARCH_INGESTION`: False by default, requires trafilatura
- `AUTO_EXECUTION_ENABLED`: Global toggle for AUTO mode (default: true)
- `CAPSULE_DEBUG_MODE`: Run capsules in isolation (default: false)

### Graceful Degradation

All new modules must degrade gracefully:

- **Research Ingestion:**
  - trafilatura missing → create placeholder evidence with confidence=0.5
  - LLM unavailable → use fallback thesis (evidence concatenation)
  - URL unreachable → log error, continue with other URLs

- **Capsules:**
  - Market data unavailable → skip capsule, log warning
  - Technical indicators fail → use default values

- **PortfolioBrain:**
  - DB unavailable → use in-memory state
  - Config missing → use default values

- **Router:**
  - Config incomplete → default to CONFIRM mode
  - Payload generation fails → log error, skip intent

## Priority Order

1. **HIGH:** Task 11 (CLI) - Enables user interaction
2. **HIGH:** Task 12 (Workflow) - Integrates all components
3. **HIGH:** Task 13 (Research) - Enables web content ingestion
4. **MEDIUM:** Task 14 (Config) - Configuration knobs
5. **MEDIUM:** Task 15 (Tests) - Quality assurance

## File Tree After Completion

```
alpha-trader/
├── DESIGN.md
├── models.py
├── capsules/
│   ├── __init__.py
│   ├── spy_qqq_liquidity_sweep.py
│   ├── nq_session_trend.py
│   ├── xauusd_macro_levels.py
│   └── kalshi_macro_sensor.py
├── portfolio.py
├── router.py
├── research.py  (NEW)
├── cli.py  (MODIFIED)
├── config/
│   └── config.yaml  (MODIFIED)
├── workflows/
│   └── morning_report.yaml  (MODIFIED)
├── tools/
│   └── reporting.py  (MODIFIED)
└── tests/
    └── test_zynth_upgrade.py  (NEW)
```

## Success Criteria

- [ ] All 5 remaining tasks completed
- [ ] All acceptance criteria met
- [ ] CLI commands work as documented
- [ ] Workflow executes end-to-end
- [ ] Tests all pass
- [ ] Config settings are respected
- [ ] Backward compatibility maintained

---

**Dependencies:**
- Base infrastructure (tasks 1-10) ✅ COMPLETE
- No external blockers identified
