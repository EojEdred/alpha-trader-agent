"""
Screen Capture Module

Handles screenshot capture for vision analysis and audit trails.
"""

import os
import base64
from io import BytesIO
from typing import Optional, Tuple
from datetime import datetime
from loguru import logger


class ScreenCapture:
    """Cross-platform screen capture utility."""
    
    def __init__(self, save_dir: str = "/tmp/trading_screenshots"):
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)
    
    def capture_full(self, filename: Optional[str] = None) -> str:
        """Capture full screen."""
        try:
            from PIL import ImageGrab
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = filename or f"full_{timestamp}.png"
            filepath = os.path.join(self.save_dir, filename)
            
            screenshot = ImageGrab.grab()
            screenshot.save(filepath)
            logger.debug(f"Full screenshot: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Full screenshot failed: {e}")
            return ""
    
    def capture_region(self, x: int, y: int, width: int, height: int, filename: Optional[str] = None) -> str:
        """Capture screen region."""
        try:
            from PIL import ImageGrab
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = filename or f"region_{x}_{y}_{timestamp}.png"
            filepath = os.path.join(self.save_dir, filename)
            
            screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
            screenshot.save(filepath)
            logger.debug(f"Region screenshot: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Region screenshot failed: {e}")
            return ""
    
    def capture_app_window(self, app_name: str) -> str:
        """Capture specific application window (macOS)."""
        try:
            import subprocess
            
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{app_name}_{timestamp}.png"
            filepath = os.path.join(self.save_dir, filename)
            
            # Use macOS screencapture with window name (-w flag)
            # This captures the window by name rather than ID
            subprocess.run([
                "screencapture", "-w", filepath
            ], check=True, timeout=10)
            
            return filepath
        except Exception as e:
            logger.error(f"App window capture failed: {e}")
            # Fallback: capture full screen and crop later
            return self.capture_full(filename)
    
    def to_base64(self, filepath: str) -> str:
        """Convert image file to base64 string."""
        try:
            with open(filepath, "rb") as f:
                return base64.b64encode(f.read()).decode()
        except Exception as e:
            logger.error(f"Base64 conversion failed: {e}")
            return ""
    
    def capture_to_base64(self, region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """Capture and immediately return base64."""
        try:
            from PIL import ImageGrab
            
            if region:
                screenshot = ImageGrab.grab(bbox=region)
            else:
                screenshot = ImageGrab.grab()
            
            buffered = BytesIO()
            screenshot.save(buffered, format="PNG")
            return base64.b64encode(buffered.getvalue()).decode()
        except Exception as e:
            logger.error(f"Capture to base64 failed: {e}")
            return ""
    
    def _get_window_id(self, app_name: str) -> Optional[int]:
        """Get window ID for macOS app using AppleScript."""
        try:
            script = f'''
            tell application "System Events"
                tell process "{app_name}"
                    set winID to id of window 1
                    return winID
                end tell
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True
            )
            win_id = result.stdout.strip()
            if win_id and win_id.isdigit():
                return int(win_id)
            return None
        except Exception:
            return None
    
    def cleanup_old(self, max_age_hours: int = 24):
        """Remove screenshots older than max_age_hours."""
        try:
            import time
            cutoff = time.time() - (max_age_hours * 3600)
            for f in os.listdir(self.save_dir):
                filepath = os.path.join(self.save_dir, f)
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
