"""
AutoHedge Adapter for Alpha Trader

Wraps the `autohedge` pip package so it can be called from the dashboard/CLI.
The adapter runs AutoHedge's director agent in a thread executor, then parses the
conversational output into structured trade recommendations.

If the `autohedge` package is not installed or no API key is available, the
adapter returns a graceful degradation response so the rest of the system keeps
working.
"""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger

from models import ExecutionMode, TradeIntent, TradeStatus, generate_intent_id
from models.decision_schemas import Direction


try:
    from autohedge.main import AutoHedge

    _AUTOHEDGE_AVAILABLE = True
except ImportError:
    _AUTOHEDGE_AVAILABLE = False
    AutoHedge = None  # type: ignore


class AutoHedgeAdapter:
    """Lightweight wrapper around the AutoHedge package."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="autohedge")

    async def run(self, task: str) -> Dict[str, Any]:
        """
        Run an AutoHedge cycle for the given task.

        Args:
            task: Natural-language task, e.g. "Analyze AAPL vs MSFT hedged pair".

        Returns:
            Dict with task, raw_messages, recommendations, and metadata.
        """
        if not _AUTOHEDGE_AVAILABLE:
            logger.warning("autohedge package not installed; returning degraded result")
            return self._degraded_result(task, reason="autohedge not installed")

        try:
            raw = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._sync_run,
                task,
            )
        except Exception as e:
            logger.error(f"AutoHedge execution failed: {e}")
            return self._degraded_result(task, reason=str(e))

        messages = self._normalize_messages(raw)
        recommendations = self._extract_recommendations(messages)

        return {
            "task": task,
            "status": "ok",
            "source": "autohedge",
            "generated_at": datetime.utcnow().isoformat(),
            "raw_messages": messages,
            "recommendations": recommendations,
            "recommendation_count": len(recommendations),
        }

    def _sync_run(self, task: str) -> Any:
        """Synchronous call to AutoHedge (runs in thread)."""
        hedge = AutoHedge(output_type="dict")
        return hedge.run(task)

    @staticmethod
    def _normalize_messages(raw: Any) -> List[Dict[str, str]]:
        """Convert AutoHedge output into a uniform list of {role, content}."""
        messages: List[Dict[str, str]] = []

        if isinstance(raw, dict):
            for role, content in raw.items():
                messages.append({"role": str(role), "content": str(content)})
        elif isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    messages.append(
                        {
                            "role": str(item.get("role", "unknown")),
                            "content": str(item.get("content", item)),
                        }
                    )
                else:
                    messages.append({"role": "unknown", "content": str(item)})
        else:
            messages.append({"role": "unknown", "content": str(raw)})

        return messages

    @staticmethod
    def _extract_recommendations(messages: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Best-effort extraction of trade recommendations from conversation text."""
        recommendations: List[Dict[str, Any]] = []

        # Concatenate all messages for holistic parsing
        full_text = "\n".join(m.get("content", "") for m in messages)

        # Find ticker symbols (uppercase 1-5 chars) near directional words
        tickers = set(re.findall(r"\b([A-Z]{1,5})\b", full_text))
        tickers = {t for t in tickers if t not in {"A", "I", "US", "USD", "ETF", "NYSE", "NASDAQ", "CEO", "CFO"}}

        direction = AutoHedgeAdapter._extract_direction(full_text)

        # Numeric fields
        entry = AutoHedgeAdapter._extract_price(full_text, "entry", "buy at", "long at")
        stop = AutoHedgeAdapter._extract_price(full_text, "stop", "stop loss")
        target = AutoHedgeAdapter._extract_price(full_text, "target", "take profit")
        size = AutoHedgeAdapter._extract_size(full_text)
        confidence = AutoHedgeAdapter._extract_confidence(full_text)

        for ticker in list(tickers)[:5]:
            recommendations.append(
                {
                    "symbol": ticker,
                    "direction": direction,
                    "entry_price": entry,
                    "stop_loss": stop,
                    "take_profit": target,
                    "size": size,
                    "confidence": confidence,
                    "reasoning": full_text[:500],
                }
            )

        return recommendations

    @staticmethod
    def _extract_direction(text: str) -> str:
        t = text.lower()
        bullish = sum(t.count(w) for w in ("bullish", "long", "buy", "overweight"))
        bearish = sum(t.count(w) for w in ("bearish", "short", "sell", "underweight"))
        if bullish > bearish:
            return "long"
        if bearish > bullish:
            return "short"
        return "neutral"

    @staticmethod
    def _extract_price(text: str, *keywords: str) -> Optional[float]:
        """Find a dollar price near one of the keywords."""
        for kw in keywords:
            # Look within 60 chars after the keyword
            for m in re.finditer(re.escape(kw), text, re.IGNORECASE):
                window = text[m.end() : m.end() + 80]
                price_match = re.search(r"\$?\s*(\d{1,6}(?:\.\d{1,4})?)", window)
                if price_match:
                    return float(price_match.group(1))
        return None

    @staticmethod
    def _extract_size(text: str) -> Optional[float]:
        for pattern in (
            r"quantity[:\s]+(\d+)",
            r"size[:\s]+(\d+)",
            r"position size[:\s]+(\d+)",
            r"(\d+)\s+shares",
            r"(\d+)\s+contracts",
        ):
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return float(m.group(1))
        return None

    @staticmethod
    def _extract_confidence(text: str) -> float:
        m = re.search(r"confidence[:\s]+(0\.\d+|1\.0|1)", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
        # Infer from conviction words
        t = text.lower()
        if any(w in t for w in ("high conviction", "strong", "very bullish", "very bearish")):
            return 0.75
        if any(w in t for w in ("medium", "moderate")):
            return 0.55
        return 0.45

    def to_trade_intent(self, rec: Dict[str, Any]) -> Optional[TradeIntent]:
        """Convert a parsed recommendation into a TradeIntent."""
        symbol = rec.get("symbol")
        direction = rec.get("direction", "neutral")
        entry = rec.get("entry_price") or 0.0
        stop = rec.get("stop_loss") or (entry * 0.95 if entry else 0.0)
        target = rec.get("take_profit") or (entry * 1.05 if entry else 0.0)

        if not symbol or direction == "neutral":
            return None

        return TradeIntent(
            id=generate_intent_id(),
            capsule_id="autohedge",
            thesis_id="autohedge",
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            conviction=rec.get("confidence", 0.5),
            invalidation_price=stop,
            time_stop=datetime.utcnow() + timedelta(days=7),
            risk_reward_ratio=abs((target - entry) / (entry - stop)) if entry and stop and entry != stop else 1.0,
            size=rec.get("size"),
            execution_mode=ExecutionMode.CONFIRM,
            venue="auto",
            tags=["autohedge"],
        )

    @staticmethod
    def _degraded_result(task: str, reason: str) -> Dict[str, Any]:
        return {
            "task": task,
            "status": "degraded",
            "source": "autohedge",
            "generated_at": datetime.utcnow().isoformat(),
            "raw_messages": [],
            "recommendations": [],
            "recommendation_count": 0,
            "reason": reason,
        }
