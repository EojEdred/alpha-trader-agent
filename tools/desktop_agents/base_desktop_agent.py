"""
Base Desktop Agent

Abstract base class for desktop application automation.
Uses pyautogui, AppleScript (macOS), and OCR for controlling trading apps.
"""

import os
import time
import subprocess
import json
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from loguru import logger


@dataclass
class DesktopActionResult:
    """Result of a desktop automation action."""
    success: bool
    action: str
    data: Dict[str, Any] = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


class BaseDesktopAgent(ABC):
    """
    Base class for desktop application automation.
    
    Features:
    - App activation via AppleScript (macOS)
    - Screen coordinate mapping
    - OCR text reading from screen regions
    - Human-like mouse movement and clicks
    - Screenshot capture for verification
    """
    
    def __init__(
        self,
        app_name: str,
        app_path: Optional[str] = None,
        verification_enabled: bool = True,
    ):
        self.app_name = app_name
        self.app_path = app_path
        self.verification_enabled = verification_enabled
        self._app_active = False
        self._screen_scale = self._detect_screen_scale()
        self.action_history: List[DesktopActionResult] = []
        
        logger.info(f"DesktopAgent[{app_name}] initialized (scale: {self._screen_scale}x)")
    
    def _detect_screen_scale(self) -> float:
        """Detect Retina display scale factor."""
        try:
            import pyautogui
            # macOS Retina detection
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"],
                capture_output=True, text=True
            )
            if "Retina" in result.stdout:
                return 2.0
            return 1.0
        except Exception:
            return 1.0
    
    def activate_app(self) -> bool:
        """Bring application to foreground using AppleScript."""
        try:
            script = f'tell application "{self.app_name}" to activate'
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
            time.sleep(1.5)  # Wait for window to come forward
            self._app_active = True
            logger.info(f"DesktopAgent[{self.app_name}] app activated")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to activate {self.app_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"Activation error: {e}")
            return False
    
    def is_app_running(self) -> bool:
        """Check if the app is currently running."""
        try:
            script = f'tell application "System Events" to (name of processes) contains "{self.app_name}"'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
            return "true" in result.stdout.lower()
        except Exception as e:
            logger.error(f"Failed to check if {self.app_name} is running: {e}")
            return False
    
    def _ensure_focus(self) -> bool:
        """Ensure the target app is frontmost before interacting."""
        try:
            script = f'tell application "System Events" to set frontmost of process "{self.app_name}" to true'
            subprocess.run(["osascript", "-e", script], check=True, timeout=5)
            time.sleep(0.3)  # Brief pause for focus to settle
            return True
        except Exception as e:
            logger.warning(f"Could not ensure focus for {self.app_name}: {e}")
            return False
    
    def click(self, x: int, y: int, clicks: int = 1, button: str = "left") -> bool:
        """Human-like click at screen coordinates with focus verification."""
        try:
            import pyautogui
            
            # Ensure app is in focus before clicking
            self._ensure_focus()
            
            # Adjust for Retina
            x = int(x / self._screen_scale)
            y = int(y / self._screen_scale)
            
            # Move with slight curve
            pyautogui.moveTo(x, y, duration=0.3 + (0.1 * clicks))
            time.sleep(0.1)
            
            if button == "right":
                pyautogui.rightClick(x, y)
            else:
                pyautogui.click(x, y, clicks=clicks)
            
            time.sleep(0.2)
            return True
        except Exception as e:
            logger.error(f"Click failed at ({x}, {y}): {e}")
            return False
    
    def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text with human-like speed."""
        try:
            import pyautogui
            self._ensure_focus()
            pyautogui.typewrite(text, interval=interval)
            return True
        except Exception as e:
            logger.error(f"Type failed: {e}")
            return False
    
    def press_key(self, key: str) -> bool:
        """Press a single key."""
        try:
            import pyautogui
            pyautogui.press(key)
            return True
        except Exception as e:
            logger.error(f"Key press failed: {e}")
            return False
    
    def hotkey(self, *keys: str) -> bool:
        """Press a keyboard shortcut."""
        try:
            import pyautogui
            self._ensure_focus()
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            logger.error(f"Hotkey failed: {e}")
            return False
    
    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """
        Capture screenshot.
        
        Args:
            region: (x, y, width, height) or None for full screen
            
        Returns:
            Path to saved screenshot
        """
        try:
            from PIL import ImageGrab
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"desktop_{self.app_name}_{timestamp}.png"
            filepath = os.path.join("/tmp", filename)
            
            if region:
                screenshot = ImageGrab.grab(bbox=region)
            else:
                screenshot = ImageGrab.grab()
            
            screenshot.save(filepath)
            logger.debug(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ""
    
    def ocr_region(self, x: int, y: int, width: int, height: int) -> str:
        """Read text from screen region using OCR."""
        try:
            from PIL import ImageGrab
            import pytesseract
            
            screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            text = pytesseract.image_to_string(screenshot)
            return text.strip()
        except ImportError:
            logger.warning("pytesseract not installed, OCR unavailable")
            return ""
        except Exception as e:
            logger.error(f"OCR failed: {e}")
            return ""
    
    def find_image_on_screen(self, image_path: str, confidence: float = 0.8) -> Optional[Tuple[int, int]]:
        """Find an image on screen and return center coordinates."""
        try:
            import pyautogui
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                return (int(center.x * self._screen_scale), int(center.y * self._screen_scale))
            return None
        except Exception as e:
            logger.error(f"Image search failed: {e}")
            return None
    
    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None):
        """Scroll at position."""
        try:
            import pyautogui
            if x is not None and y is not None:
                pyautogui.scroll(amount, x=int(x/self._screen_scale), y=int(y/self._screen_scale))
            else:
                pyautogui.scroll(amount)
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
    
    def wait_for_image(self, image_path: str, timeout: int = 30, confidence: float = 0.8) -> bool:
        """Wait for an image to appear on screen."""
        start = time.time()
        while time.time() - start < timeout:
            location = self.find_image_on_screen(image_path, confidence)
            if location:
                return True
            time.sleep(0.5)
        logger.warning(f"Timeout waiting for image: {image_path}")
        return False
    
    def record_action(self, action: str, success: bool, data: Dict = None, error: str = None):
        """Record action for audit trail."""
        result = DesktopActionResult(
            success=success,
            action=action,
            data=data or {},
            error=error,
        )
        self.action_history.append(result)
    
    @abstractmethod
    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions from the app."""
        pass
    
    @abstractmethod
    def place_order(self, order: Dict[str, Any]) -> DesktopActionResult:
        """
        Place an order through the desktop app.
        
        Args:
            order: Dict with keys:
                - symbol: str
                - side: str ("long" or "short")
                - quantity: int
                - order_type: str ("market", "limit", "stop")
                - price: Optional[float] (for limit/stop orders)
        """
        pass
