"""
Alpha Trader Production Engine

Wires together all components and runs the actual trading loop.
Updates the shared SystemState for the TUI and API to consume.

Usage:
    from dexter.engine import TradingEngine
    engine = TradingEngine(dry_run=True)
    await engine.start()
"""

import asyncio
import os
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from loguru import logger

from dexter.state import (
    get_state, SystemMode, AgentStatus,
    TradeRecord, RiskSnapshot,
)
from models import (
    TradeIntent, RiskDecision, ExecutionMode, TradeStatus,
    generate_intent_id,
)
from portfolio import PortfolioBrain
from router import ExecutionRouter
from tools.unified_execution_router import UnifiedExecutionRouter
from tools.rate_limiter import RateLimiter
from tools.trade_counter import TradeCounter
from tools.order_tracker import OrderTracker
from strategies.registry import StrategyRegistry
from strategies.data_feed import DataFeed
from strategies.confluence import ConfluenceEngine
from agents.sentiment_agent import SentimentAgent
from agents.research_manager import ResearchManager
from agents.risk_manager import RiskManager, PortfolioManager
from tools.memory_log import MemoryLog
from tools.reporting_fixed import log_trade
from models.decision_schemas import TradeProposal, Verdict


class TradingEngine:
    """
    Production trading engine.

    Responsibilities:
    - Initialize and wire all subsystems
    - Run the main trading loop
    - Execute trades through the full pipeline
    - Update shared state for UI consumption
    """

    def __init__(self, dry_run: bool = True, venues: Optional[List[str]] = None, strategy_names: Optional[List[str]] = None):
        self.dry_run = dry_run
        self.venues = venues or ["oanda", "topstep", "schwab"]
        self.strategy_names = strategy_names or ["vwap_trend", "ema_cross_heikin"]
        self.running = False
        self._task: Optional[asyncio.Task] = None

        # Subsystems
        self.portfolio = PortfolioBrain(config={
            "max_risk_per_trade_pct": 1.0,
            "consecutive_loss_limit": 3,
            "correlation_threshold": 0.7,
        })
        self.router = ExecutionRouter(config={
            "execution_modes": {
                "oanda": {"auto_enabled": True, "max_size_auto": 10000},
                "kalshi": {"auto_enabled": True},
                "schwab": {"auto_enabled": False},
                "topstep": {"auto_enabled": False},
            }
        })
        self.executor = UnifiedExecutionRouter(config={})
        self.rate_limiter = RateLimiter()
        self.trade_counter = TradeCounter()
        self.order_tracker = OrderTracker()
        self._intents: Dict[str, TradeIntent] = {}
        self._pending_intents: Dict[str, TradeIntent] = {}

        # Strategy layer
        self.registry = StrategyRegistry()
        self.registry.discover()
        self.data_feed = DataFeed()
        self.confluence = ConfluenceEngine(self.registry, min_agreement=2, min_confidence=0.6)

        # Multi-agent pipeline
        self.sentiment_agent = SentimentAgent()
        self.research_manager = ResearchManager()
        self.risk_manager = RiskManager()
        self.portfolio_manager = PortfolioManager()
        self.memory_log = MemoryLog()

        # Symbol universe per venue
        self.symbols = {
            "oanda": ["XAU_USD", "EUR_USD", "GBP_USD", "USD_JPY"],
            "schwab": ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"],
            "topstep": ["NQ1!", "ES1!", "CL1!", "GC1!"],
        }
        
        # Data source mapping per symbol
        self.data_sources = {
            "XAU_USD": "oanda",
            "EUR_USD": "oanda",
            "GBP_USD": "oanda",
            "USD_JPY": "oanda",
            "SPY": "schwab",
            "QQQ": "schwab",
            "AAPL": "schwab",
            "TSLA": "schwab",
            "NVDA": "schwab",
            # Futures: TradingView has free real-time + historical data
            "NQ1!": "tradingview",
            "ES1!": "tradingview",
            "CL1!": "tradingview",
            "GC1!": "tradingview",
        }

        # Register agents in state
        state = get_state()
        state.dry_run = dry_run
        state.active_venues = self.venues
        for venue in self.venues:
            state.register_agent(f"{venue}_api")
        state.register_agent("tradingview_browser")
        state.register_agent("schwab_web_browser")
        state.register_agent("propfirm_browser")
        state.register_agent("tos_desktop")
        state.register_agent("tradovate_desktop")
        state.register_agent("vision_analyzer")
        for name in self.registry.list_strategies():
            state.register_agent(f"strategy_{name['name']}")

    async def start(self):
        """Start the trading engine."""
        state = get_state()
        state.set_mode(SystemMode.STARTING)
        state.add_log("Engine initializing...")

        logger.info("TradingEngine starting (dry_run={})", self.dry_run)

        # Initialize subsystems
        state.update_agent("tradingview_browser", AgentStatus.IDLE, "initialized")
        state.update_agent("schwab_web_browser", AgentStatus.IDLE, "initialized")
        state.update_agent("propfirm_browser", AgentStatus.IDLE, "initialized")
        state.update_agent("tos_desktop", AgentStatus.IDLE, "initialized")
        state.update_agent("tradovate_desktop", AgentStatus.IDLE, "initialized")
        state.update_agent("vision_analyzer", AgentStatus.IDLE, "initialized")

        for venue in self.venues:
            state.update_agent(f"{venue}_api", AgentStatus.IDLE, "initialized")

        state.set_mode(SystemMode.RUNNING)
        state.add_log(f"Engine started — venues: {', '.join(self.venues)} — dry_run={self.dry_run}")
        self.running = True

        # Start background tasks
        self._task = asyncio.create_task(self._main_loop())
        asyncio.create_task(self._heartbeat())
        asyncio.create_task(self._risk_monitor())

    async def stop(self):
        """Stop the trading engine."""
        self.running = False
        state = get_state()
        state.set_mode(SystemMode.STOPPED)
        state.add_log("Engine stopped")
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _main_loop(self):
        """Main trading loop — generates and executes trades."""
        while self.running:
            try:
                await self._tick()
                await asyncio.sleep(5)  # 5-second tick for responsive demo
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Main loop error")
                get_state().add_log(f"Engine error: {e}")
                await asyncio.sleep(5)

    async def _tick(self):
        """Single trading tick: multi-agent pipeline."""
        state = get_state()
        if state.mode != SystemMode.RUNNING:
            return

        # ─── PHASE 1: Fetch Market Data ───
        symbol_map = {}
        for venue in self.venues:
            for sym in self.symbols.get(venue, []):
                source = self.data_sources.get(sym, "yahoo")
                symbol_map[sym] = source

        try:
            data = await self.data_feed.fetch_multi(symbol_map, period="1d", interval="5m")
        except Exception as e:
            logger.warning(f"Data feed failed: {e}")
            data = {"ohlcv": {}}

        if not data.get("ohlcv"):
            return

        # ─── PHASE 2: Technical Analysts (Strategy Confluence) ───
        confluence_results = await self.confluence.run(data)
        if not confluence_results:
            return

        state.add_log(f"Confluence: {len(confluence_results)} symbols with analyst agreement")

        # ─── PHASE 3: Sentiment Analyst (per symbol) ───
        all_reports = []
        for result in confluence_results:
            # Technical reports from confluence
            tech_reports = self.confluence.to_analyst_reports(result)
            all_reports.extend(tech_reports)

            # Sentiment analysis
            try:
                sentiment_report = await self.sentiment_agent.analyze(result.symbol)
                all_reports.append(sentiment_report)
                state.update_agent("sentiment_analyst", AgentStatus.BUSY, f"analyzing {result.symbol}")
            except Exception as e:
                logger.warning(f"Sentiment analysis failed for {result.symbol}: {e}")

        # ─── PHASE 4: Research Manager (synthesize all reports) ───
        for result in confluence_results:
            symbol = result.symbol
            symbol_reports = [r for r in all_reports if r.symbol == symbol]

            # Get current price
            price_data = None
            if symbol in data["ohlcv"]:
                last_price = data["ohlcv"][symbol]["close"].iloc[-1]
                price_data = {"last": last_price}

            try:
                research_plan = await self.research_manager.synthesize(symbol, symbol_reports, price_data)
                self.memory_log.record_research_plan(research_plan)
                state.update_agent("research_manager", AgentStatus.BUSY, f"plan for {symbol}: {research_plan.recommendation.value}")
            except Exception as e:
                logger.error(f"Research Manager failed for {symbol}: {e}")
                continue

            # Skip if research says hold/neutral
            if research_plan.recommendation.value == "neutral" or research_plan.confidence < 0.5:
                state.add_log(f"Research Manager: HOLD {symbol} (confidence too low)")
                continue

            # ─── PHASE 5: Trader (create proposal) ───
            # Use the best confluence signal as the proposal base
            majority_signals = [s for s in result.raw_signals if s.direction == result.direction]
            best_signal = max(majority_signals, key=lambda s: s.conviction)

            # Determine venue
            venue = "schwab"
            if any(x in symbol.upper() for x in ["NQ", "ES", "CL", "GC"]):
                venue = "topstep"
            elif "/" in symbol or symbol.upper() in ["XAUUSD", "EURUSD"]:
                venue = "oanda"

            proposal = TradeProposal(
                symbol=symbol,
                action=research_plan.recommendation,
                entry_price=best_signal.entry_price,
                stop_loss=best_signal.stop_price,
                take_profit=best_signal.target_price,
                position_size=1,  # Sized by portfolio brain
                risk_amount=abs(best_signal.entry_price - best_signal.stop_price),
                risk_reward_ratio=abs(best_signal.target_price - best_signal.entry_price) / abs(best_signal.entry_price - best_signal.stop_price)
                if best_signal.entry_price != best_signal.stop_price else 2.0,
                rationale=research_plan.strategic_actions,
                time_horizon="intraday",
                venue=venue,
            )
            self.memory_log.record_trade_proposal(proposal)
            state.update_agent("trader", AgentStatus.BUSY, f"proposing {symbol} {proposal.action.value}")

            # ─── PHASE 6: Risk Manager (assess proposal) ───
            portfolio_state = {
                "equity": 100000,  # Would come from actual account
                "open_positions": len(self._intents),
                "day_pnl": 0,
                "consecutive_losses": getattr(self.portfolio, 'consecutive_losses', 0),
                "max_drawdown_today": 0,
            }

            try:
                risk_assessment = await self.risk_manager.assess(proposal, research_plan, portfolio_state)
                self.memory_log.record_risk_assessment(risk_assessment)
                state.update_agent("risk_manager", AgentStatus.BUSY, f"{risk_assessment.verdict.value} {symbol}")
            except Exception as e:
                logger.error(f"Risk Manager failed for {symbol}: {e}")
                continue

            # ─── PHASE 7: Portfolio Manager (final decision) ───
            final_decision = self.portfolio_manager.decide(research_plan, risk_assessment, proposal)
            self.memory_log.record_final_decision(final_decision)
            state.update_agent("portfolio_manager", AgentStatus.BUSY, f"{final_decision.verdict.value} {symbol}")

            if final_decision.verdict == Verdict.APPROVE:
                state.add_log(
                    f"✅ APPROVED: {symbol} {proposal.action.value.upper()} "
                    f"@ ${proposal.entry_price:.2f} (R:R {proposal.risk_reward_ratio:.1f}:1)"
                )

                # Convert to TradeIntent and execute
                from models import TradeIntent, generate_intent_id
                intent = TradeIntent(
                    id=generate_intent_id(),
                    capsule_id="multi_agent",
                    thesis_id=research_plan.rationale[:100],
                    symbol=symbol,
                    direction=proposal.action.value,
                    entry_price=proposal.entry_price,
                    stop_price=proposal.stop_loss,
                    target_price=proposal.take_profit,
                    conviction=research_plan.confidence,
                    invalidation_price=proposal.stop_loss,
                    time_stop=datetime.utcnow() + timedelta(hours=4),
                    risk_reward_ratio=proposal.risk_reward_ratio,
                    size=final_decision.approved_size or 1,
                    venue=proposal.venue,
                    evidence_citations=[r.agent_name for r in symbol_reports],
                )
                await self.submit_intent(intent)

            elif final_decision.verdict == Verdict.REJECT:
                state.add_log(f"❌ REJECTED: {symbol} — {risk_assessment.reasoning[:80]}")
            else:
                state.add_log(f"⏸️ HOLD: {symbol} — {final_decision.reasoning[:80]}")

    async def _execute_intent(self, intent: TradeIntent):
        """Execute a single approved intent through the unified router."""
        state = get_state()

        if not await self.rate_limiter.acquire(intent.venue):
            state.add_log(f"Rate limited on {intent.venue} — skipping {intent.symbol}")
            return

        if not self.trade_counter.can_trade(intent.venue):
            state.add_log(f"Daily trade limit reached for {intent.venue}")
            return

        agent_name = f"{intent.venue}_api"
        state.update_agent(agent_name, AgentStatus.BUSY, f"executing {intent.symbol} {intent.direction}")

        try:
            risk_decision = RiskDecision(intent_id=intent.id, approved=True)
            result = await self.executor.execute_intent(
                intent, risk_decision, dry_run=self.dry_run
            )

            trade = TradeRecord(
                id=intent.id,
                symbol=intent.symbol,
                direction=intent.direction,
                size=intent.size,
                venue=intent.venue,
                method=result.method.value if hasattr(result.method, 'value') else str(result.method),
                status="filled" if result.success else "failed",
                timestamp=datetime.utcnow(),
                pnl=result.fill_price if result.success else None,
                error=result.error if not result.success else None,
            )
            state.add_trade(trade)
            self.trade_counter.record_trade(intent.venue)

            try:
                log_trade(
                    venue=intent.venue,
                    symbol=intent.symbol,
                    side=intent.direction,
                    quantity=int(intent.size or 0),
                    price=result.fill_price,
                    order_type="MARKET",
                    order_id=intent.id,
                    pnl=0.0,
                    status=trade.status,
                    notes=f"Executed via {trade.method}",
                    details={"dry_run": self.dry_run, "source": "engine"},
                )
            except Exception as e:
                logger.warning(f"Failed to log trade to audit DB: {e}")

            if result.success:
                state.add_log(
                    f"✓ {intent.symbol} {intent.direction} @ {intent.venue} "
                    f"via {trade.method} — fill=${result.fill_price}"
                )
            else:
                state.add_log(
                    f"✗ {intent.symbol} {intent.direction} @ {intent.venue} FAILED: {result.error}"
                )

        except Exception as e:
            logger.exception("Execution error")
            state.add_log(f"Exception executing {intent.symbol}: {e}")
        finally:
            state.update_agent(agent_name, AgentStatus.IDLE)

    async def _execute_plan(self, plan):
        """Execute a single plan through the unified router."""
        state = get_state()

        # Find the original intent
        intent = self._find_intent(plan.intent_id)
        if not intent:
            return

        # Check rate limits
        if not await self.rate_limiter.acquire(intent.venue):
            state.add_log(f"Rate limited on {intent.venue} — skipping {intent.symbol}")
            return

        # Check trade count limits
        if not self.trade_counter.can_trade(intent.venue):
            state.add_log(f"Daily trade limit reached for {intent.venue}")
            return

        # Mark agent busy
        agent_name = f"{intent.venue}_api"
        state.update_agent(agent_name, AgentStatus.BUSY, f"executing {intent.symbol} {intent.direction}")

        try:
            # Execute via unified router
            risk_decision = RiskDecision(intent_id=intent.id, approved=True)
            result = await self.executor.execute_intent(
                intent, risk_decision, dry_run=self.dry_run
            )

            # Record trade
            trade = TradeRecord(
                id=intent.id,
                symbol=intent.symbol,
                direction=intent.direction,
                size=intent.size,
                venue=intent.venue,
                method=result.method.value if hasattr(result.method, 'value') else str(result.method),
                status="filled" if result.success else "failed",
                timestamp=datetime.utcnow(),
                pnl=result.fill_price if result.success else None,
                error=result.error if not result.success else None,
            )
            state.add_trade(trade)
            self.trade_counter.record_trade(intent.venue)

            try:
                log_trade(
                    venue=intent.venue,
                    symbol=intent.symbol,
                    side=intent.direction,
                    quantity=int(intent.size or 0),
                    price=result.fill_price,
                    order_type="MARKET",
                    order_id=intent.id,
                    pnl=0.0,
                    status=trade.status,
                    notes=f"Executed via {trade.method}",
                    details={"dry_run": self.dry_run, "source": "engine_plan"},
                )
            except Exception as e:
                logger.warning(f"Failed to log trade to audit DB: {e}")

            if result.success:
                state.add_log(
                    f"✓ {intent.symbol} {intent.direction} @ {intent.venue} "
                    f"via {trade.method} — fill={result.fill_price}"
                )
            else:
                state.add_log(
                    f"✗ {intent.symbol} {intent.direction} @ {intent.venue} FAILED: {result.error}"
                )

        except Exception as e:
            logger.exception("Execution error")
            state.add_log(f"Exception executing {intent.symbol}: {e}")

        finally:
            state.update_agent(agent_name, AgentStatus.IDLE)

    async def _heartbeat(self):
        """Periodic heartbeat to update agent statuses."""
        while self.running:
            try:
                await asyncio.sleep(5)
                state = get_state()
                # Randomly set an agent to busy briefly to show activity
                if random.random() < 0.1:
                    agents = list(state.agents.keys())
                    if agents:
                        agent = random.choice(agents)
                        state.update_agent(agent, AgentStatus.BUSY, "polling")
                        await asyncio.sleep(1)
                        state.update_agent(agent, AgentStatus.IDLE)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _risk_monitor(self):
        """Update risk snapshot periodically."""
        while self.running:
            try:
                await asyncio.sleep(3)
                state = get_state()
                snapshot = RiskSnapshot(
                    circuit_breaker_active=bool(
                        getattr(self.executor, '_circuit_breaker_active', False)
                    ),
                    daily_trades={
                        v: self.trade_counter.get_count(v) for v in self.venues
                    },
                    daily_limits={v: 10 for v in self.venues},
                    rate_limited={
                        v: not await self.rate_limiter.acquire(v) for v in self.venues
                    },
                    consecutive_losses=getattr(self.portfolio, 'consecutive_losses', 0),
                )
                state.update_risk(snapshot)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _generate_signals(self) -> List[TradeIntent]:
        """Generate trade signals from registered strategies using live market data."""
        intents = []

        # Build symbol map for data feed
        symbol_map = {}
        for venue in self.venues:
            for sym in self.symbols.get(venue, []):
                source = self.data_sources.get(sym, "yahoo")
                symbol_map[sym] = source

        if not symbol_map:
            return []

        # Fetch market data
        try:
            data = await self.data_feed.fetch_multi(symbol_map, period="1d", interval="5m")
        except Exception as e:
            logger.warning(f"Data feed failed: {e}")
            return []

        if not data.get("ohlcv"):
            return []

        # Run strategies
        all_signals = self.registry.run_all(data)

        for strategy_name, signals in all_signals.items():
            for signal in signals:
                if not self.registry.get(strategy_name).should_trade(signal.symbol, signal):
                    continue

                intent = self.registry.to_trade_intents([signal])[0]
                intents.append(intent)
                logger.info(
                    f"Signal: {signal.symbol} {signal.direction} "
                    f"via {intent.venue} (strategy: {strategy_name}, conviction: {signal.conviction})"
                )

        return intents

    def _find_intent(self, intent_id: str) -> Optional[TradeIntent]:
        """Find intent by ID from in-memory store."""
        return self._intents.get(intent_id)

    async def submit_intent(self, intent: TradeIntent):
        """Queue or execute an intent based on venue execution mode."""
        self._intents[intent.id] = intent
        mode = self.router._determine_execution_mode(
            intent, RiskDecision(intent_id=intent.id, approved=True)
        )

        intent.execution_mode = mode
        if mode.value.lower() == "confirm":
            intent.status = TradeStatus.PENDING
            self._pending_intents[intent.id] = intent
            get_state().add_log(
                f"⏳ PENDING approval: {intent.symbol} {intent.direction} x{intent.size} @ {intent.venue}"
            )
        else:
            await self._execute_intent(intent)

    def get_pending_intents(self) -> List[TradeIntent]:
        return list(self._pending_intents.values())

    async def approve_intent(self, intent_id: str) -> bool:
        intent = self._pending_intents.pop(intent_id, None)
        if not intent:
            return False
        intent.status = TradeStatus.APPROVED
        get_state().add_log(f"✅ Approved {intent.symbol} {intent.direction}, executing...")
        await self._execute_intent(intent)
        return True

    def reject_intent(self, intent_id: str) -> bool:
        intent = self._pending_intents.pop(intent_id, None)
        if not intent:
            return False
        intent.status = TradeStatus.REJECTED
        get_state().add_log(f"❌ Rejected {intent.symbol} {intent.direction}")
        return True

    async def _fetch_manual_entry(self, symbol: str, venue: str) -> float:
        """Fetch a real reference price for a manual trade."""
        try:
            if venue.lower() == "oanda":
                from tools.oanda import oanda_get_price
                price = await oanda_get_price(symbol)
                if "bid" in price and "ask" in price:
                    return round((price["bid"] + price["ask"]) / 2, 4)
            elif venue.lower() == "schwab":
                from tools.schwab import schwab_get_price
                price = await schwab_get_price(symbol)
                if "last" in price:
                    return round(price["last"], 2)
                if "bid" in price and "ask" in price:
                    return round((price["bid"] + price["ask"]) / 2, 2)
        except Exception as e:
            logger.warning(f"Could not fetch real price for {symbol}@{venue}: {e}")
        return round(random.uniform(100, 500), 2)

    async def place_manual_trade(self, symbol: str, direction: str, size: int, venue: str) -> str:
        """Place a manual trade via the engine. Returns the intent id."""
        state = get_state()
        entry = await self._fetch_manual_entry(symbol, venue)
        stop = round(entry * (0.97 if direction == "long" else 1.03), 4)
        target = round(entry * (1.05 if direction == "long" else 0.95), 4)

        intent = TradeIntent(
            id=generate_intent_id(),
            capsule_id="manual",
            thesis_id="manual",
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            conviction=0.8,
            invalidation_price=stop,
            time_stop=datetime.utcnow() + timedelta(hours=1),
            risk_reward_ratio=2.0,
            size=size,
            venue=venue,
        )

        state.add_log(f"Manual trade submitted: {symbol} {direction} x{size} @ {venue}")
        await self.submit_intent(intent)
        return intent.id
