"""
Computer Vision Module

Uses GPT-4V and OCR to analyze screenshots of trading platforms.
Provides visual confirmation, chart analysis, and error detection.
"""

from .vision_analyzer import TradingVisionAnalyzer
from .screen_capture import ScreenCapture
from .ocr_reader import OCRReader

__all__ = [
    "TradingVisionAnalyzer",
    "ScreenCapture",
    "OCRReader",
]