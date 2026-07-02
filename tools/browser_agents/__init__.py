"""
Browser Agents Module

Autonomous browser-based trading agents using browser-use + Playwright.
Supports TradingView, Prop Firm web platforms, and Schwab web interface.
"""

from .base_browser_agent import BaseBrowserAgent, BrowserActionResult
from .tradingview_agent import TradingViewAgent
from .propfirm_agent import PropFirmAgent
from .schwab_web_agent import SchwabWebAgent

__all__ = [
    "BaseBrowserAgent",
    "BrowserActionResult",
    "TradingViewAgent",
    "PropFirmAgent",
    "SchwabWebAgent",
]