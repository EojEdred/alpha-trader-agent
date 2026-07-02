"""
Shared Live State for Alpha Trader

Thread-safe singleton that holds the runtime state of the trading system.
The TUI subscribes to this state and refreshes every tick.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime
from enum import Enum


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


class SystemMode(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class AgentInfo:
    name: str
    status: AgentStatus = AgentStatus.OFFLINE
    last_action: str = ""
    last_updated: Optional[datetime] = None
    error: Optional[str] = None


@dataclass
class TradeRecord:
    id: str
    symbol: str
    direction: str
    size: Optional[int]
    venue: str
    method: str
    status: str
    timestamp: datetime
    pnl: Optional[float] = None
    error: Optional[str] = None


@dataclass
class RiskSnapshot:
    circuit_breaker_active: bool = False
    daily_trades: Dict[str, int] = field(default_factory=dict)
    daily_limits: Dict[str, int] = field(default_factory=dict)
    rate_limited: Dict[str, bool] = field(default_factory=dict)
    consecutive_losses: int = 0


class SystemState:
    """Thread-safe singleton for live system state."""

    _instance: Optional["SystemState"] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self):
        self.mode: SystemMode = SystemMode.STOPPED
        self.dry_run: bool = True
        self.started_at: Optional[datetime] = None
        self.uptime_seconds: float = 0.0
        self.active_venues: List[str] = []

        self.agents: Dict[str, AgentInfo] = {}
        self.trades: List[TradeRecord] = []
        self.risk: RiskSnapshot = RiskSnapshot()

        self.logs: List[str] = []
        self.max_logs: int = 500

        self._subscribers: List[asyncio.Queue] = []

    # ─── Agent Management ───

    def register_agent(self, name: str):
        self.agents[name] = AgentInfo(name=name)

    def update_agent(self, name: str, status: AgentStatus, action: str = "", error: Optional[str] = None):
        if name not in self.agents:
            self.register_agent(name)
        agent = self.agents[name]
        agent.status = status
        agent.last_action = action
        agent.last_updated = datetime.utcnow()
        agent.error = error

    # ─── Trade Management ───

    def add_trade(self, trade: TradeRecord):
        self.trades.insert(0, trade)
        if len(self.trades) > 200:
            self.trades = self.trades[:200]

    # ─── Risk Management ───

    def update_risk(self, snapshot: RiskSnapshot):
        self.risk = snapshot

    # ─── Logging ───

    def add_log(self, message: str):
        ts = datetime.utcnow().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        self.logs.append(line)
        if len(self.logs) > self.max_logs:
            self.logs = self.logs[-self.max_logs:]
        self._notify(line)

    # ─── Subscriptions ───

    def _notify(self, line: str):
        for q in self._subscribers:
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self._subscribers:
            self._subscribers.remove(q)

    # ─── Mode Control ───

    def set_mode(self, mode: SystemMode):
        self.mode = mode
        if mode == SystemMode.RUNNING and self.started_at is None:
            self.started_at = datetime.utcnow()

    def tick_uptime(self):
        if self.started_at and self.mode in (SystemMode.RUNNING, SystemMode.PAUSED):
            self.uptime_seconds = (datetime.utcnow() - self.started_at).total_seconds()


# Global state accessor
def get_state() -> SystemState:
    return SystemState()
