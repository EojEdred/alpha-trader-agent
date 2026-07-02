"""
Desktop Automation Agents Module

Controls desktop trading applications using pyautogui, AppleScript, and OCR.
Supports ThinkOrSwim, TradingView Desktop, NinjaTrader, and Tradovate.
"""

from .base_desktop_agent import BaseDesktopAgent
from .tos_automation import ThinkOrSwimDesktopAgent
from .tradovate_desktop import TradovateDesktopAgent

__all__ = [
    "BaseDesktopAgent",
    "ThinkOrSwimDesktopAgent",
    "TradovateDesktopAgent",
]