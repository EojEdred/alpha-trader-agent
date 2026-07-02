"""
Order Status Tracker

Background polling for working orders to detect fills, partials, and rejections.
Integrates with all execution methods (API, Browser, Desktop).
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from loguru import logger


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    WORKING = "working"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class TrackedOrder:
    """An order being tracked by the OrderTracker."""
    order_id: str
    venue: str
    symbol: str
    side: str
    quantity: float
    status: OrderStatus
    filled_quantity: float = 0.0
    avg_fill_price: Optional[float] = None
    last_price: Optional[float] = None
    submitted_at: datetime = field(default_factory=datetime.utcnow)
    last_checked_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_active(self) -> bool:
        """Check if order is still active (working or partial)."""
        return self.status in (OrderStatus.WORKING, OrderStatus.PARTIAL, OrderStatus.SUBMITTED)


class OrderTracker:
    """
    Tracks order status via background polling.
    
    Usage:
        tracker = OrderTracker()
        tracker.add_order(order_id="OANDA_123", venue="oanda", ...)
        # tracker starts polling automatically
        
        status = tracker.get_status("OANDA_123")
        # Returns current known status
    """
    
    def __init__(
        self,
        poll_interval_seconds: float = 5.0,
        max_poll_duration_minutes: float = 60.0,
    ):
        self.poll_interval = poll_interval_seconds
        self.max_poll_duration = timedelta(minutes=max_poll_duration_minutes)
        
        self._orders: Dict[str, TrackedOrder] = {}
        self._callbacks: List[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        logger.info("OrderTracker initialized")
    
    def start(self):
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("OrderTracker polling started")
    
    def stop(self):
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("OrderTracker polling stopped")
    
    def add_order(
        self,
        order_id: str,
        venue: str,
        symbol: str,
        side: str,
        quantity: float,
        status: OrderStatus = OrderStatus.SUBMITTED,
        metadata: Dict[str, Any] = None,
    ):
        """Add an order to be tracked."""
        self._orders[order_id] = TrackedOrder(
            order_id=order_id,
            venue=venue,
            symbol=symbol,
            side=side,
            quantity=quantity,
            status=status,
            metadata=metadata or {},
        )
        logger.info(f"Tracking order {order_id} ({symbol} on {venue})")
        
        # Auto-start if not running
        if not self._running:
            self.start()
    
    def get_status(self, order_id: str) -> Optional[TrackedOrder]:
        """Get current status of a tracked order."""
        return self._orders.get(order_id)
    
    def get_all_active(self) -> List[TrackedOrder]:
        """Get all orders that are still active."""
        return [o for o in self._orders.values() if o.is_active()]
    
    def on_status_change(self, callback: Callable):
        """Register a callback for status changes."""
        self._callbacks.append(callback)
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self._running:
            try:
                await self._poll_all()
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"OrderTracker poll error: {e}")
                await asyncio.sleep(self.poll_interval)
    
    async def _poll_all(self):
        """Poll all active orders."""
        now = datetime.utcnow()
        
        for order_id, order in list(self._orders.items()):
            if not order.is_active():
                continue
            
            # Check max poll duration
            if now - order.submitted_at > self.max_poll_duration:
                logger.warning(f"Order {order_id} polling timed out after {self.max_poll_duration}")
                order.status = OrderStatus.EXPIRED
                await self._notify_change(order)
                continue
            
            try:
                updated = await self._poll_single(order)
                if updated:
                    await self._notify_change(order)
            except Exception as e:
                logger.error(f"Failed to poll order {order_id}: {e}")
    
    async def _poll_single(self, order: TrackedOrder) -> bool:
        """Poll a single order. Returns True if status changed."""
        old_status = order.status
        venue = order.venue.lower()
        
        # Route to venue-specific status check
        if venue == "oanda":
            status = await self._check_oanda(order)
        elif venue == "schwab":
            status = await self._check_schwab(order)
        elif venue in ("topstep", "apex"):
            status = await self._check_prop_firm(order)
        elif venue == "thinkorswim":
            status = await self._check_tos(order)
        else:
            # No polling available for this venue
            return False
        
        if status and status != old_status:
            order.status = status
            order.last_checked_at = datetime.utcnow()
            return True
        
        order.last_checked_at = datetime.utcnow()
        return False
    
    async def _check_oanda(self, order: TrackedOrder) -> Optional[OrderStatus]:
        """Check OANDA order status."""
        try:
            from tools.oanda import get_order_status
            result = await get_order_status(order.order_id)
            return self._map_status(result.get("status", ""))
        except Exception:
            return None
    
    async def _check_schwab(self, order: TrackedOrder) -> Optional[OrderStatus]:
        """Check Schwab order status."""
        try:
            from tools.schwab import get_order_status
            result = await get_order_status(order.order_id)
            return self._map_status(result.get("status", ""))
        except Exception:
            return None
    
    async def _check_prop_firm(self, order: TrackedOrder) -> Optional[OrderStatus]:
        """Check prop firm order status via browser agent."""
        try:
            from tools.browser_agents import PropFirmAgent
            agent = PropFirmAgent(platform=order.venue)
            await agent.initialize()
            result = await agent.get_order_status(order.order_id)
            await agent.shutdown()
            return self._map_status(result.get("status", ""))
        except Exception:
            return None
    
    async def _check_tos(self, order: TrackedOrder) -> Optional[OrderStatus]:
        """Check ThinkOrSwim order status via desktop agent."""
        try:
            from tools.desktop_agents import ThinkOrSwimDesktopAgent
            agent = ThinkOrSwimDesktopAgent()
            # TOS doesn't expose order IDs easily via desktop
            # This would need OCR of the order status window
            return None
        except Exception:
            return None
    
    def _map_status(self, raw_status: str) -> Optional[OrderStatus]:
        """Map raw broker status to OrderStatus enum."""
        raw = raw_status.lower()
        
        mapping = {
            "pending": OrderStatus.PENDING,
            "submitted": OrderStatus.SUBMITTED,
            "working": OrderStatus.WORKING,
            "open": OrderStatus.WORKING,
            "partial": OrderStatus.PARTIAL,
            "partially_filled": OrderStatus.PARTIAL,
            "filled": OrderStatus.FILLED,
            "completed": OrderStatus.FILLED,
            "cancelled": OrderStatus.CANCELLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        
        return mapping.get(raw)
    
    async def _notify_change(self, order: TrackedOrder):
        """Notify all registered callbacks of a status change."""
        logger.info(f"Order {order.order_id} status changed: {order.status.value}")
        
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(order)
                else:
                    callback(order)
            except Exception as e:
                logger.error(f"Order status callback failed: {e}")
