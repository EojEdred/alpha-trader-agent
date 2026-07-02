"""
2FA / CAPTCHA Human-in-the-Loop Handler

When browser agents encounter 2FA, CAPTCHA, or security questions,
this handler:
1. Captures a screenshot of the challenge
2. Sends a Telegram alert to the human
3. Polls for session validity
4. Times out after 5 minutes and falls back to SIGNAL_ONLY
"""

import asyncio
import os
from typing import Optional, Callable
from datetime import datetime, timedelta
from loguru import logger


class TwoFactorHandler:
    """
    Handles 2FA, CAPTCHA, and security challenges during browser automation.
    
    Usage:
        handler = TwoFactorHandler()
        if await handler.detect_challenge(browser_agent):
            success = await handler.wait_for_resolution(timeout_seconds=300)
            if not success:
                # Fallback to SIGNAL_ONLY
    """
    
    def __init__(self, timeout_seconds: float = 300):
        self.timeout_seconds = timeout_seconds
        self._resolved = asyncio.Event()
        self._resolution_result = False
        self._challenge_detected_at: Optional[datetime] = None
    
    async def detect_challenge(self, browser_agent) -> bool:
        """
        Detect if the current page shows a 2FA/CAPTCHA/security challenge.
        
        Returns:
            True if a challenge was detected and human was notified.
        """
        try:
            # Take screenshot of current state
            screenshot_path = await browser_agent.screenshot("challenge_detected.png")
            
            # Check for challenge indicators via vision or OCR
            challenge_type = await self._identify_challenge_type(browser_agent)
            
            if challenge_type:
                self._challenge_detected_at = datetime.utcnow()
                logger.warning(f"Challenge detected: {challenge_type}")
                await self._notify_human(challenge_type, screenshot_path)
                return True
            
            return False
        except Exception as e:
            logger.error(f"Challenge detection failed: {e}")
            return False
    
    async def _identify_challenge_type(self, browser_agent) -> Optional[str]:
        """Identify what type of challenge is present."""
        try:
            # Use a quick browser task to identify the challenge
            result = await browser_agent.run_task(
                "Look at the current page. Is there a 2FA code input, SMS verification prompt, "
                "CAPTCHA image, security question, or 'Verify your identity' message? "
                "Return ONLY one of: 2FA, CAPTCHA, SECURITY_QUESTION, NONE",
                max_steps=5
            )
            
            if result.success:
                response = result.data.get("result", "").upper()
                if "2FA" in response or "SMS" in response or "CODE" in response:
                    return "2FA"
                elif "CAPTCHA" in response:
                    return "CAPTCHA"
                elif "SECURITY" in response or "QUESTION" in response:
                    return "SECURITY_QUESTION"
            
            return None
        except Exception:
            return None
    
    async def _notify_human(self, challenge_type: str, screenshot_path: str):
        """Send Telegram notification to human."""
        try:
            from tools.delivery import send_telegram
            
            msg = f"🔐 *{challenge_type} REQUIRED*\n\n"
            msg += f"Platform: browser automation\n"
            msg += f"Detected at: {datetime.utcnow().strftime('%H:%M:%S')} UTC\n"
            msg += f"Screenshot: {screenshot_path}\n\n"
            
            if challenge_type == "2FA":
                msg += "Please complete the 2FA/SMS verification in the browser.\n"
                msg += "The agent will resume automatically once you're logged in."
            elif challenge_type == "CAPTCHA":
                msg += "CAPTCHA detected. Please solve it in the browser.\n"
                msg += "The agent cannot solve CAPTCHAs automatically."
            elif challenge_type == "SECURITY_QUESTION":
                msg += "Security question detected. Please answer it in the browser."
            
            msg += f"\n⏱ Auto-timeout in {self.timeout_seconds // 60} minutes."
            
            await send_telegram(message=msg)
            logger.info(f"Sent {challenge_type} notification to human")
        except Exception as e:
            logger.error(f"Failed to notify human: {e}")
    
    async def wait_for_resolution(self, browser_agent, check_interval: float = 10.0) -> bool:
        """
        Wait for human to resolve the challenge.
        
        Args:
            browser_agent: The browser agent to check
            check_interval: How often to check if resolved
        
        Returns:
            True if resolved, False if timed out.
        """
        if not self._challenge_detected_at:
            return True
        
        deadline = self._challenge_detected_at + timedelta(seconds=self.timeout_seconds)
        
        while datetime.utcnow() < deadline:
            remaining = (deadline - datetime.utcnow()).total_seconds()
            logger.info(f"Waiting for challenge resolution... {remaining:.0f}s remaining")
            
            # Check if we're past the challenge page
            try:
                is_resolved = await self._check_if_resolved(browser_agent)
                if is_resolved:
                    logger.info("Challenge resolved by human")
                    self._resolution_result = True
                    self._resolved.set()
                    await self._notify_resolution_success()
                    return True
            except Exception as e:
                logger.debug(f"Resolution check failed: {e}")
            
            await asyncio.sleep(check_interval)
        
        logger.warning(f"Challenge timed out after {self.timeout_seconds}s")
        await self._notify_timeout()
        return False
    
    async def _check_if_resolved(self, browser_agent) -> bool:
        """Check if the challenge page is no longer present."""
        try:
            result = await browser_agent.run_task(
                "Check if there's still a 2FA prompt, CAPTCHA, security question, or login challenge on this page. "
                "Return ONLY: YES (challenge still present) or NO (challenge resolved)",
                max_steps=5
            )
            
            if result.success:
                response = result.data.get("result", "").upper()
                return "NO" in response
            
            return False
        except Exception:
            return False
    
    async def _notify_resolution_success(self):
        """Notify that challenge was resolved."""
        try:
            from tools.delivery import send_telegram
            await send_telegram(message="✅ *Challenge resolved!*\nBrowser automation resuming.")
        except Exception:
            pass
    
    async def _notify_timeout(self):
        """Notify that challenge timed out."""
        try:
            from tools.delivery import send_telegram
            await send_telegram(
                message="⏱ *Challenge timed out*\nFalling back to SIGNAL_ONLY. Manual execution required."
            )
        except Exception:
            pass
    
    def reset(self):
        """Reset handler state for next challenge."""
        self._resolved.clear()
        self._resolution_result = False
        self._challenge_detected_at = None
