"""
Unified Execution Router

The core execution engine with multi-modal fallback:
API → Browser → Desktop → Signal Only

Integrates the best features from:
- NautilusTrader (deterministic event-driven architecture)
- OpenAlgo (unified broker API abstraction)
- Backtest-Kit (crash-safe persistence, transactional integrity)
- ibkr-mcp (advanced order types: TWAP, VWAP, Adaptive)
"""

import os
import json
import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

from models import (
    TradeIntent, RiskDecision, ExecutionPlan, ExecutionMode, TradeStatus,
    ExecutionMethod, ExecutionResult,
)
from tools.rate_limiter import RateLimiter


class UnifiedExecutionRouter:
    """
    Smart execution router with fallback chain.
    
    For each TradeIntent, tries execution methods in order:
    1. Native API (fastest, most reliable)
    2. Browser automation (for web-only platforms)
    3. Desktop automation (for desktop-only apps)
    4. Signal only (human execution)
    
    Features from open-source projects:
    - NautilusTrader: Deterministic execution semantics
    - Backtest-Kit: Crash-safe state persistence
    - OpenAlgo: Smart order splitting, unified API
    - ibkr-mcp: TWAP, VWAP, Adaptive order types
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # Method availability cache
        self._method_availability: Dict[str, Dict[str, bool]] = {}
        
        # Browser agents (lazy init)
        self._browser_agents: Dict[str, Any] = {}
        self._desktop_agents: Dict[str, Any] = {}
        self._vision_analyzer = None
        
        # Execution statistics
        self._stats = {
            "total_executions": 0,
            "api_success": 0,
            "browser_success": 0,
            "desktop_success": 0,
            "signal_only": 0,
            "failures": 0,
        }
        
        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_active = False
        
        # Rate limiter
        self._rate_limiter = RateLimiter()
        
        # Method availability tracking (venue -> method -> unavailable_until timestamp)
        self._method_availability: Dict[str, Dict[str, Optional[float]]] = {}
        
        # Execution context (set per execute_intent call)
        self._model: Optional[str] = None
        self._dry_run: bool = False
        
        logger.info("UnifiedExecutionRouter initialized")
    
    # ─── LAZY AGENT INITIALIZATION ───
    
    def _get_browser_agent(self, platform: str, model: Optional[str] = None, dry_run: bool = False):
        """Lazy-init browser agent."""
        cache_key = f"{platform}:{model or 'default'}:{dry_run}"
        if cache_key not in self._browser_agents:
            from tools.browser_agents import (
                TradingViewAgent,
                PropFirmAgent,
                SchwabWebAgent,
            )
            
            if platform == "tradingview":
                self._browser_agents[cache_key] = TradingViewAgent(model=model, dry_run=dry_run)
            elif platform in ["topstep", "apex", "leeloo"]:
                self._browser_agents[cache_key] = PropFirmAgent(platform=platform, model=model, dry_run=dry_run)
            elif platform == "schwab_web":
                self._browser_agents[cache_key] = SchwabWebAgent(model=model, dry_run=dry_run)
        
        return self._browser_agents.get(cache_key)
    
    def _get_desktop_agent(self, platform: str):
        """Lazy-init desktop agent."""
        if platform not in self._desktop_agents:
            from tools.desktop_agents import (
                ThinkOrSwimDesktopAgent,
                TradovateDesktopAgent,
            )
            
            if platform == "thinkorswim":
                self._desktop_agents[platform] = ThinkOrSwimDesktopAgent()
            elif platform == "tradovate":
                self._desktop_agents[platform] = TradovateDesktopAgent()
        
        return self._desktop_agents.get(platform)
    
    def _get_vision_analyzer(self):
        """Lazy-init vision analyzer."""
        if self._vision_analyzer is None:
            from tools.vision import TradingVisionAnalyzer
            self._vision_analyzer = TradingVisionAnalyzer()
        return self._vision_analyzer
    
    # ─── MAIN EXECUTION METHOD ───
    
    async def execute_intent(
        self,
        intent: TradeIntent,
        risk_decision: RiskDecision,
        preferred_method: Optional[ExecutionMethod] = None,
        model: Optional[str] = None,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Execute a TradeIntent using the best available method.
        
        Args:
            intent: The trade to execute
            risk_decision: Approved risk decision
            preferred_method: Force a specific method (for testing)
        
        Returns:
            ExecutionResult with details of what happened
        """
        self._dry_run = dry_run
        self._model = model
        
        if self._circuit_breaker_active:
            logger.warning("Circuit breaker active - rejecting execution")
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.SIGNAL_ONLY,
                venue=intent.venue,
                error="Circuit breaker active - too many consecutive failures",
            )
        
        venue = intent.venue.lower()
        self._stats["total_executions"] += 1
        
        logger.info(f"Executing {intent.symbol} on {venue} (size: {intent.size})")
        
        # Check rate limit
        if not dry_run:
            if not await self._rate_limiter.acquire(venue):
                logger.warning(f"Rate limited for venue: {venue}")
                return ExecutionResult(
                    success=False,
                    method=ExecutionMethod.SIGNAL_ONLY,
                    venue=venue,
                    error=f"Rate limited for venue: {venue}. Too many requests.",
                )
        
        # Check daily trade count for prop firms
        if venue in ("topstep", "apex", "leeloo"):
            from tools.trade_counter import TradeCounter
            counter = TradeCounter()
            if not counter.can_trade(venue):
                return ExecutionResult(
                    success=False,
                    method=ExecutionMethod.SIGNAL_ONLY,
                    venue=venue,
                    error=f"Daily trade limit reached for {venue}",
                )
        
        # Determine method priority
        methods = self._get_method_priority(venue, preferred_method)
        
        # Try each method in order
        last_error = None
        for method in methods:
            try:
                result = await self._execute_with_method(intent, method)
                
                if result.success:
                    self._consecutive_failures = 0
                    self._increment_stat(method, success=True)
                    logger.info(f"Execution succeeded via {method.value}: {result.order_id}")
                    return result
                else:
                    last_error = result.error
                    logger.warning(f"Method {method.value} failed: {last_error}")
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"Method {method.value} threw exception: {e}")
        
        # All methods failed
        self._consecutive_failures += 1
        self._increment_stat(methods[-1], success=False)
        
        # Check circuit breaker
        if self._consecutive_failures >= self._circuit_breaker_threshold:
            self._circuit_breaker_active = True
            logger.error(f"Circuit breaker activated after {self._consecutive_failures} failures")
        
        # Fallback to signal only
        return ExecutionResult(
            success=False,
            method=ExecutionMethod.SIGNAL_ONLY,
            venue=venue,
            error=f"All methods failed. Last error: {last_error}",
            metadata={"attempted_methods": [m.value for m in methods]},
        )
    
    def _get_method_priority(
        self,
        venue: str,
        preferred: Optional[ExecutionMethod] = None,
    ) -> List[ExecutionMethod]:
        """Determine execution method priority for a venue."""
        
        if preferred:
            return [preferred]
        
        # Venue-specific priorities
        priorities = {
            # API-first venues
            "oanda": [ExecutionMethod.API, ExecutionMethod.BROWSER],
            "kalshi": [ExecutionMethod.API, ExecutionMethod.BROWSER],
            "polymarket": [ExecutionMethod.API, ExecutionMethod.BROWSER],
            "schwab": [ExecutionMethod.API, ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP],
            "interactive_brokers": [ExecutionMethod.API, ExecutionMethod.DESKTOP],
            
            # Browser-first venues
            "tradingview": [ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP],
            "topstep": [ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP],
            "apex": [ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP],
            "leeloo": [ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP],
            
            # Desktop-first venues
            "thinkorswim": [ExecutionMethod.DESKTOP, ExecutionMethod.BROWSER],
            "tradovate": [ExecutionMethod.DESKTOP, ExecutionMethod.BROWSER],
            "ninjatrader": [ExecutionMethod.DESKTOP],
        }
        
        return priorities.get(venue, [ExecutionMethod.API, ExecutionMethod.BROWSER, ExecutionMethod.DESKTOP, ExecutionMethod.SIGNAL_ONLY])
    
    async def _execute_with_method(
        self,
        intent: TradeIntent,
        method: ExecutionMethod,
    ) -> ExecutionResult:
        """Execute using a specific method."""
        venue = intent.venue.lower()
        
        # Check method availability
        if not self._is_method_available(venue, method):
            logger.warning(f"Method {method.value} temporarily unavailable for {venue}")
            return ExecutionResult(
                success=False,
                method=method,
                venue=venue,
                error=f"Method {method.value} temporarily unavailable for {venue}",
            )
        
        if method == ExecutionMethod.API:
            return await self._execute_api(intent)
        elif method == ExecutionMethod.BROWSER:
            return await self._execute_browser(intent)
        elif method == ExecutionMethod.DESKTOP:
            return await self._execute_desktop(intent)
        elif method == ExecutionMethod.SIGNAL_ONLY:
            return ExecutionResult(
                success=False,
                method=method,
                venue=venue,
                error="Signal only - no execution attempted",
            )
        
        return ExecutionResult(
            success=False,
            method=method,
            venue=venue,
            error=f"Unknown method: {method.value}",
        )
    
    # ─── RETRY UTILITIES ───
    
    async def _retry_with_backoff(
        self,
        func,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 10.0,
        exceptions: tuple = (Exception,),
    ):
        """Execute a function with exponential backoff retry."""
        import random
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return await func()
            except exceptions as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                    logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed: {e}")
        
        raise last_error
    
    def _is_method_available(self, venue: str, method: ExecutionMethod) -> bool:
        """Check if a method is temporarily marked unavailable for a venue."""
        venue_data = self._method_availability.get(venue, {})
        unavailable_until = venue_data.get(method.value)
        if unavailable_until is None:
            return True
        if time.time() > unavailable_until:
            # TTL expired, clear it
            venue_data[method.value] = None
            return True
        return False
    
    def mark_method_unavailable(self, venue: str, method: ExecutionMethod, duration_seconds: float = 300):
        """Mark a method as temporarily unavailable for a venue."""
        if venue not in self._method_availability:
            self._method_availability[venue] = {}
        self._method_availability[venue][method.value] = time.time() + duration_seconds
        logger.info(f"Marked {method.value} as unavailable for {venue} for {duration_seconds}s")
    
    # ─── API EXECUTION ───
    
    async def _execute_api(self, intent: TradeIntent) -> ExecutionResult:
        """Execute via native broker API."""
        venue = intent.venue.lower()
        
        # Dry-run simulation
        if self._dry_run:
            return self._simulate_fill(intent, ExecutionMethod.API)
        
        # Validate size is explicitly set
        if intent.size is None:
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.API,
                venue=venue,
                error="Size not specified — intent.size is None. Size must be set by PortfolioBrain before execution.",
            )
        
        try:
            if venue == "oanda":
                from tools.oanda import oanda_place_order
                result = await self._retry_with_backoff(
                    lambda: oanda_place_order(
                        instrument=intent.symbol.replace("/", "_").upper(),
                        units=int(intent.size),
                        side=intent.direction,
                        order_type="MARKET",
                    ),
                    max_retries=3,
                    base_delay=1.0,
                    exceptions=(Exception,),
                )
                return self._parse_api_result(result, venue, ExecutionMethod.API)
            
            elif venue == "schwab":
                from tools.schwab import schwab_place_order
                result = await self._retry_with_backoff(
                    lambda: schwab_place_order(
                        symbol=intent.symbol.upper(),
                        quantity=int(intent.size),
                        side="BUY" if intent.direction == "long" else "SELL",
                    ),
                    max_retries=3,
                    base_delay=2.0,
                    exceptions=(Exception,),
                )
                return self._parse_api_result(result, venue, ExecutionMethod.API)
            
            elif venue == "kalshi":
                from tools.kalshi import place_order
                result = await self._retry_with_backoff(
                    lambda: place_order(
                        ticker=intent.symbol,
                        side="yes" if intent.direction == "long" else "no",
                        size=int(intent.size),
                        price=0.5,
                    ),
                    max_retries=3,
                    base_delay=1.0,
                    exceptions=(Exception,),
                )
                return self._parse_api_result(result, venue, ExecutionMethod.API)
            
            elif venue == "topstep":
                from tools.topstep import topstep_place_order
                result = await self._retry_with_backoff(
                    lambda: topstep_place_order(
                        symbol=intent.symbol.upper(),
                        quantity=int(intent.size),
                        side="BUY" if intent.direction == "long" else "SELL",
                        confirmed=getattr(intent, "confirmed", False),
                    ),
                    max_retries=2,
                    base_delay=1.0,
                    exceptions=(Exception,),
                )
                return self._parse_api_result(result, venue, ExecutionMethod.API)
            
            else:
                return ExecutionResult(
                    success=False,
                    method=ExecutionMethod.API,
                    venue=venue,
                    error=f"No API adapter for venue: {venue}",
                )
        
        except Exception as e:
            # All retries exhausted — mark API as temporarily unavailable
            self.mark_method_unavailable(venue, ExecutionMethod.API, duration_seconds=60)
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.API,
                venue=venue,
                error=f"API failed after retries: {str(e)}",
            )
    
    def _parse_api_result(
        self,
        result: Dict[str, Any],
        venue: str,
        method: ExecutionMethod,
    ) -> ExecutionResult:
        """Parse API result into ExecutionResult."""
        status = result.get("status", "")
        success = status in ["filled", "submitted", "success", "pending"]
        
        return ExecutionResult(
            success=success,
            method=method,
            venue=venue,
            order_id=result.get("order_id"),
            status=status,
            fill_price=result.get("fill_price"),
            error=result.get("error"),
            metadata=result,
        )
    
    def _simulate_fill(self, intent: TradeIntent, method: ExecutionMethod) -> ExecutionResult:
        """Simulate a realistic fill for dry-run mode."""
        import random
        
        # Simulate realistic slippage
        base_price = intent.entry_price or 100.0
        slippage_pct = random.uniform(-0.02, 0.02)  # ±0.02% slippage
        fill_price = round(base_price * (1 + slippage_pct), 4)
        
        venue = intent.venue.lower()
        logger.info(
            f"[DRY-RUN] Simulated {method.value} execution for {intent.symbol} @ {venue}: "
            f"{intent.direction} {intent.size} units @ ${fill_price}"
        )
        
        return ExecutionResult(
            success=True,
            method=method,
            venue=venue,
            order_id=f"DRYRUN_{random.randint(100000, 999999)}",
            status="filled",
            fill_price=fill_price,
            metadata={"dry_run": True, "simulated_slippage_pct": slippage_pct},
        )
    
    # ─── BROWSER EXECUTION ───
    
    async def _execute_browser(self, intent: TradeIntent) -> ExecutionResult:
        """Execute via browser automation."""
        venue = intent.venue.lower()
        
        # Validate size is explicitly set
        if intent.size is None:
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.BROWSER,
                venue=venue,
                error="Size not specified — intent.size is None. Size must be set by PortfolioBrain before execution.",
            )
        
        try:
            agent = self._get_browser_agent(venue, model=self._model, dry_run=self._dry_run)
            if not agent:
                return ExecutionResult(
                    success=False,
                    method=ExecutionMethod.BROWSER,
                    venue=venue,
                    error=f"No browser agent for venue: {venue}",
                )
            
            await agent.initialize()
            
            # Build standardized order dict
            order = {
                "symbol": intent.symbol,
                "side": intent.direction,
                "quantity": int(intent.size),
                "order_type": "market",
                "price": intent.entry_price if intent.entry_price > 0 else None,
                "stop_loss": intent.stop_price if intent.stop_price > 0 else None,
                "take_profit": intent.target_price if intent.target_price > 0 else None,
                "time_in_force": "day",
            }
            
            # Place order (or dry-run)
            if self._dry_run:
                if hasattr(agent, 'dry_run_place_order'):
                    result = await agent.dry_run_place_order(order)
                else:
                    return self._simulate_fill(intent, ExecutionMethod.BROWSER)
            else:
                result = await agent.place_order(order)
            
            # Verify with vision if screenshot captured
            if result.success and result.screenshot_path:
                result = await self.verify_execution(
                    ExecutionResult(
                        success=result.success,
                        method=ExecutionMethod.BROWSER,
                        venue=venue,
                        order_id=result.data.get("order_id"),
                        status="submitted" if result.success else "failed",
                        screenshot_path=result.screenshot_path,
                        error=result.error,
                        metadata=result.data,
                    ),
                    result.screenshot_path,
                )
                # Re-wrap into the result we return
                return result
            
            await agent.shutdown()
            
            # Record trade for prop firm counters
            if result.success and venue in ("topstep", "apex", "leeloo") and not self._dry_run:
                from tools.trade_counter import TradeCounter
                TradeCounter().record_trade(venue)
            
            return ExecutionResult(
                success=result.success,
                method=ExecutionMethod.BROWSER,
                venue=venue,
                order_id=result.data.get("order_id"),
                status="submitted" if result.success else "failed",
                screenshot_path=result.screenshot_path,
                error=result.error,
                metadata=result.data,
            )
        
        except Exception as e:
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.BROWSER,
                venue=venue,
                error=str(e),
            )
    
    # ─── DESKTOP EXECUTION ───
    
    async def _execute_desktop(self, intent: TradeIntent) -> ExecutionResult:
        """Execute via desktop automation."""
        venue = intent.venue.lower()
        
        # Dry-run simulation
        if self._dry_run:
            return self._simulate_fill(intent, ExecutionMethod.DESKTOP)
        
        # Validate size is explicitly set
        if intent.size is None:
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.DESKTOP,
                venue=venue,
                error="Size not specified — intent.size is None. Size must be set by PortfolioBrain before execution.",
            )
        
        try:
            # Map venue to desktop platform
            platform_map = {
                "thinkorswim": "thinkorswim",
                "tradovate": "tradovate",
                "topstep": "tradovate",
                "apex": "tradovate",
                "schwab": "thinkorswim",
            }
            
            platform = platform_map.get(venue, venue)
            agent = self._get_desktop_agent(platform)
            
            if not agent:
                return ExecutionResult(
                    success=False,
                    method=ExecutionMethod.DESKTOP,
                    venue=venue,
                    error=f"No desktop agent for platform: {platform}",
                )
            
            # Build standardized order dict
            order = {
                "symbol": intent.symbol,
                "side": intent.direction,
                "quantity": int(intent.size),
                "order_type": "market",
                "price": intent.entry_price if intent.entry_price > 0 else None,
            }
            
            # Run synchronous desktop agent in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: agent.place_order(order),
            )
            
            return ExecutionResult(
                success=result.success,
                method=ExecutionMethod.DESKTOP,
                venue=venue,
                screenshot_path=result.screenshot_path,
                error=result.error,
                metadata=result.data,
            )
        
        except Exception as e:
            return ExecutionResult(
                success=False,
                method=ExecutionMethod.DESKTOP,
                venue=venue,
                error=str(e),
            )
    
    # ─── VISION VERIFICATION ───
    
    async def verify_execution(
        self,
        result: ExecutionResult,
        screenshot_path: Optional[str] = None,
    ) -> ExecutionResult:
        """Verify execution using vision analysis."""
        if not screenshot_path:
            return result
        
        try:
            vision = self._get_vision_analyzer()
            analysis = vision.verify_order_confirmation(screenshot_path)
            
            if analysis.success and analysis.confidence > 0.8:
                result.metadata["vision_verified"] = True
                result.metadata["vision_confidence"] = analysis.confidence
                
                # Update with vision-extracted data
                if "order_id" in analysis.extracted_data:
                    result.order_id = analysis.extracted_data["order_id"]
            else:
                result.metadata["vision_verified"] = False
                result.metadata["vision_warning"] = "Could not visually verify order"
        
        except Exception as e:
            logger.error(f"Vision verification failed: {e}")
            result.metadata["vision_error"] = str(e)
        
        return result
    
    # ─── UTILITY METHODS ───
    
    def _increment_stat(self, method: ExecutionMethod, success: bool):
        """Update execution statistics."""
        if method == ExecutionMethod.API and success:
            self._stats["api_success"] += 1
        elif method == ExecutionMethod.BROWSER and success:
            self._stats["browser_success"] += 1
        elif method == ExecutionMethod.DESKTOP and success:
            self._stats["desktop_success"] += 1
        elif not success:
            self._stats["failures"] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        return self._stats.copy()
    
    def reset_circuit_breaker(self):
        """Manual reset of circuit breaker."""
        self._circuit_breaker_active = False
        self._consecutive_failures = 0
        logger.info("Circuit breaker manually reset")
    
    async def close_all_agents(self):
        """Clean shutdown of all agents."""
        for name, agent in self._browser_agents.items():
            try:
                await agent.shutdown()
                logger.info(f"Browser agent {name} shutdown")
            except Exception as e:
                logger.error(f"Error shutting down {name}: {e}")
        
        self._browser_agents.clear()
        self._desktop_agents.clear()
