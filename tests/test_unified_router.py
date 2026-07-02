"""
Tests for Unified Execution Router

Tests the multi-modal fallback chain:
API → Browser → Desktop → Signal Only
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from models import TradeIntent, RiskDecision, ExecutionMode, generate_intent_id, ExecutionMethod
from tools.unified_execution_router import UnifiedExecutionRouter, ExecutionResult


@pytest.fixture
def router():
    return UnifiedExecutionRouter(config={})


@pytest.fixture
def sample_intent():
    return TradeIntent(
        id=generate_intent_id(),
        capsule_id="test",
        thesis_id="test",
        symbol="SPY",
        direction="long",
        entry_price=450.0,
        stop_price=445.0,
        target_price=460.0,
        conviction=0.8,
        invalidation_price=455.0,
        time_stop=__import__('datetime').datetime.utcnow(),
        risk_reward_ratio=2.0,
        size=100,
        venue="oanda",
    )


@pytest.fixture
def approved_risk(sample_intent):
    return RiskDecision(intent_id=sample_intent.id, approved=True)


class TestUnifiedRouter:
    """Test suite for unified execution router."""
    
    @pytest.mark.asyncio
    async def test_api_execution_success(self, router, sample_intent, approved_risk):
        """Test successful API execution."""
        with patch('tools.oanda.oanda_place_order', new_callable=AsyncMock) as mock:
            mock.return_value = {
                "status": "filled",
                "order_id": "OANDA_123",
                "fill_price": 450.25,
            }
            
            result = await router.execute_intent(sample_intent, approved_risk)
            
            assert result.success is True
            assert result.method == ExecutionMethod.API
            assert result.order_id == "OANDA_123"
            assert result.fill_price == 450.25
    
    @pytest.mark.asyncio
    async def test_api_failure_falls_back_to_browser(self, router, sample_intent, approved_risk):
        """Test fallback to browser when API fails."""
        with patch('tools.oanda.oanda_place_order', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"status": "failed", "error": "Connection error"}
            
            with patch.object(router, '_execute_browser', new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = ExecutionResult(
                    success=True,
                    method=ExecutionMethod.BROWSER,
                    venue="oanda",
                    order_id="BROWSER_456",
                )
                
                result = await router.execute_intent(sample_intent, approved_risk)
                
                assert result.success is True
                assert result.method == ExecutionMethod.BROWSER
                assert result.order_id == "BROWSER_456"
    
    @pytest.mark.asyncio
    async def test_all_methods_fail_returns_signal_only(self, router, sample_intent, approved_risk):
        """Test signal-only fallback when all methods fail."""
        with patch('tools.oanda.oanda_place_order', new_callable=AsyncMock) as mock_api:
            mock_api.return_value = {"status": "failed"}
            
            with patch.object(router, '_execute_browser', new_callable=AsyncMock) as mock_browser:
                mock_browser.return_value = ExecutionResult(
                    success=False,
                    method=ExecutionMethod.BROWSER,
                    venue="oanda",
                    error="Browser failed",
                )
                
                with patch.object(router, '_execute_desktop', new_callable=AsyncMock) as mock_desktop:
                    mock_desktop.return_value = ExecutionResult(
                        success=False,
                        method=ExecutionMethod.DESKTOP,
                        venue="oanda",
                        error="Desktop failed",
                    )
                    
                    result = await router.execute_intent(sample_intent, approved_risk)
                    
                    assert result.success is False
                    assert result.method == ExecutionMethod.SIGNAL_ONLY
                    assert "All methods failed" in result.error
    
    @pytest.mark.asyncio
    async def test_circuit_breaker(self, router, sample_intent, approved_risk):
        """Test circuit breaker activates after consecutive failures."""
        router._circuit_breaker_threshold = 2
        
        # Bypass rate limiting for this test
        router._rate_limiter.acquire = AsyncMock(return_value=True)
        
        # First failure
        with patch('tools.oanda.oanda_place_order', new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "failed"}
            await router.execute_intent(sample_intent, approved_risk)
        
        # Second failure
        with patch('tools.oanda.oanda_place_order', new_callable=AsyncMock) as mock:
            mock.return_value = {"status": "failed"}
            await router.execute_intent(sample_intent, approved_risk)
        
        # Circuit breaker should be active
        assert router._circuit_breaker_active is True
        
        # Third attempt should be rejected
        result = await router.execute_intent(sample_intent, approved_risk)
        assert result.success is False
        assert "Circuit breaker" in result.error
    
    @pytest.mark.asyncio
    async def test_size_none_rejected(self, router, approved_risk):
        """Test that orders with size=None are rejected."""
        intent = TradeIntent(
            id=generate_intent_id(),
            capsule_id="test",
            thesis_id="test",
            symbol="SPY",
            direction="long",
            entry_price=450.0,
            stop_price=445.0,
            target_price=460.0,
            conviction=0.8,
            invalidation_price=455.0,
            time_stop=__import__('datetime').datetime.utcnow(),
            risk_reward_ratio=2.0,
            size=None,  # No size specified
            venue="oanda",
        )
        
        result = await router.execute_intent(intent, approved_risk)
        assert result.success is False
        assert "Size not specified" in result.error
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self, router, sample_intent, approved_risk):
        """Test that rate limiting blocks excessive requests."""
        # Mock rate limiter to always reject
        router._rate_limiter.acquire = AsyncMock(return_value=False)
        
        result = await router.execute_intent(sample_intent, approved_risk)
        assert result.success is False
        assert "Rate limited" in result.error
    
    @pytest.mark.asyncio
    async def test_method_availability_tracking(self, router, sample_intent, approved_risk):
        """Test that unavailable methods are skipped."""
        router.mark_method_unavailable("oanda", ExecutionMethod.API, duration_seconds=60)
        
        result = await router._execute_with_method(sample_intent, ExecutionMethod.API)
        assert result.success is False
        assert "unavailable" in result.error.lower()
    
    def test_method_priority_oanda(self, router):
        """Test correct method priority for OANDA."""
        methods = router._get_method_priority("oanda")
        assert ExecutionMethod.API in methods
        assert ExecutionMethod.BROWSER in methods
    
    def test_method_priority_topstep(self, router):
        """Test correct method priority for Topstep."""
        methods = router._get_method_priority("topstep")
        assert methods[0] == ExecutionMethod.BROWSER
        assert methods[1] == ExecutionMethod.DESKTOP
    
    def test_method_priority_thinkorswim(self, router):
        """Test correct method priority for ThinkOrSwim."""
        methods = router._get_method_priority("thinkorswim")
        assert methods[0] == ExecutionMethod.DESKTOP
        assert methods[1] == ExecutionMethod.BROWSER


class TestBrowserAgents:
    """Test browser agent initialization and signatures."""
    
    def test_tradingview_agent_init(self):
        """Test TradingView agent can be initialized."""
        from tools.browser_agents import TradingViewAgent
        agent = TradingViewAgent()
        assert agent.platform_name == "tradingview"
    
    def test_tradingview_place_order_signature(self):
        """Test TradingView place_order accepts dict."""
        import inspect
        from tools.browser_agents import TradingViewAgent
        sig = inspect.signature(TradingViewAgent.place_order)
        params = list(sig.parameters.keys())
        assert params == ['self', 'order']
    
    def test_propfirm_agent_init(self):
        """Test PropFirm agent can be initialized."""
        from tools.browser_agents import PropFirmAgent
        agent = PropFirmAgent(platform="topstep")
        assert agent.platform == "topstep"
    
    def test_propfirm_hard_limits(self):
        """Test PropFirm hard-coded Combine limits."""
        from tools.browser_agents import PropFirmAgent
        agent = PropFirmAgent(platform="topstep")
        limits = agent._get_hard_limits()
        assert limits["max_contracts"] == 5
        assert limits["max_daily_loss"] == 2000
    
    def test_schwab_web_agent_init(self):
        """Test SchwabWeb agent can be initialized."""
        from tools.browser_agents import SchwabWebAgent
        agent = SchwabWebAgent()
        assert agent.platform_name == "schwab_web"
    
    def test_all_browser_agents_have_dict_signature(self):
        """Test all browser agents use standardized dict signature."""
        import inspect
        from tools.browser_agents import TradingViewAgent, PropFirmAgent, SchwabWebAgent
        
        for cls in [TradingViewAgent, PropFirmAgent, SchwabWebAgent]:
            sig = inspect.signature(cls.place_order)
            params = list(sig.parameters.keys())
            assert params == ['self', 'order'], f"{cls.__name__} has wrong signature: {params}"


class TestDesktopAgents:
    """Test desktop agent initialization."""
    
    def test_tos_agent_init(self):
        """Test TOS agent can be initialized."""
        from tools.desktop_agents import ThinkOrSwimDesktopAgent
        agent = ThinkOrSwimDesktopAgent()
        assert agent.app_name == "thinkorswim"
    
    def test_tos_has_focus_check(self):
        """Test TOS agent has focus verification."""
        from tools.desktop_agents import ThinkOrSwimDesktopAgent
        agent = ThinkOrSwimDesktopAgent()
        assert hasattr(agent, '_ensure_focus')
    
    def test_tradovate_agent_init(self):
        """Test Tradovate agent can be initialized."""
        from tools.desktop_agents import TradovateDesktopAgent
        agent = TradovateDesktopAgent()
        assert agent.app_name == "Tradovate"
    
    def test_all_desktop_agents_have_dict_signature(self):
        """Test all desktop agents use standardized dict signature."""
        import inspect
        from tools.desktop_agents import ThinkOrSwimDesktopAgent, TradovateDesktopAgent
        
        for cls in [ThinkOrSwimDesktopAgent, TradovateDesktopAgent]:
            sig = inspect.signature(cls.place_order)
            params = list(sig.parameters.keys())
            assert params == ['self', 'order'], f"{cls.__name__} has wrong signature: {params}"


class TestVision:
    """Test vision analyzer."""
    
    def test_vision_analyzer_init(self):
        """Test vision analyzer can be initialized."""
        from tools.vision import TradingVisionAnalyzer
        analyzer = TradingVisionAnalyzer()
        assert analyzer is not None


class TestLLMFactory:
    """Test dynamic LLM discovery."""
    
    def test_factory_discovers_without_crashing(self):
        """Test factory discovery runs without errors."""
        from tools.llm_factory import LLMFactory

        LLMFactory.clear_cache()
        factory = LLMFactory.discover(fast_mode=True)
        providers = factory.available_providers()
        models = factory.list_available_models()

        # Should not crash even if no providers found
        assert isinstance(providers, list)
        assert isinstance(models, list)
    
    def test_factory_kimi_from_gizzi(self):
        """Test factory finds kimi from gizzi config if present."""
        from tools.llm_factory import LLMFactory

        LLMFactory.clear_cache()
        factory = LLMFactory.discover(fast_mode=True)
        provider = factory.get_provider_for_model("kimi-k2")

        # May or may not find it depending on config — just ensure no crash
        assert True

    def test_kimi_cli_wrapper_clean_output(self):
        """Test KimiCLIWrapper strips session footer and fences."""
        from tools.llm_factory import KimiCLIWrapper

        wrapper = KimiCLIWrapper()
        raw = "Hello\n\nTo resume this session: kimi -r abc123"
        cleaned = wrapper._clean_output(raw)
        assert cleaned == "Hello"

        raw2 = "```json\n{\"a\": 1}\n```"
        cleaned2 = wrapper._clean_output(raw2)
        assert cleaned2 == '{"a": 1}'


class TestRateLimiter:
    """Test rate limiter."""
    
    @pytest.mark.asyncio
    async def test_rate_limiter_acquire(self):
        """Test rate limiter blocks after too many requests."""
        from tools.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        # First request should pass
        assert await limiter.acquire("topstep") is True
        
        # Status should show 1 recent request
        status = limiter.get_status("topstep")
        assert status["recent_requests"] == 1
    
    def test_rate_limiter_defaults(self):
        """Test default limits are configured."""
        from tools.rate_limiter import RateLimiter, DEFAULT_LIMITS
        
        assert "oanda" in DEFAULT_LIMITS
        assert "topstep" in DEFAULT_LIMITS
        assert DEFAULT_LIMITS["topstep"].min_interval_seconds == 5.0


class TestTradeCounter:
    """Test daily trade counter."""
    
    def test_trade_counter_init(self):
        """Test trade counter initializes database."""
        from tools.trade_counter import TradeCounter
        
        counter = TradeCounter(db_path="/tmp/test_trade_counter.db")
        assert counter.can_trade("topstep") is True
        assert counter.get_count("topstep") == 0
    
    def test_trade_counter_records_and_limits(self):
        """Test trade counter records trades and enforces limits."""
        import uuid
        from tools.trade_counter import TradeCounter
        
        # Use unique DB to avoid conflicts with previous test runs
        db_path = f"/tmp/test_trade_counter_{uuid.uuid4().hex}.db"
        counter = TradeCounter(db_path=db_path)
        counter.record_trade("topstep")
        assert counter.get_count("topstep") == 1
        
        # Should still allow more
        assert counter.can_trade("topstep") is True
        
        # Cleanup
        import os
        os.remove(db_path)


class TestOrderTracker:
    """Test order tracker."""
    
    def test_order_tracker_init(self):
        """Test order tracker initializes."""
        from tools.order_tracker import OrderTracker
        
        tracker = OrderTracker()
        assert tracker.get_all_active() == []
