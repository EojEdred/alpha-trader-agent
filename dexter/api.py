"""
Alpha Trader API Server

FastAPI backend providing:
- REST endpoints for system state, trades, agents, positions, pending approvals
- WebSocket endpoint for live state/log streaming
- Static file serving for the built React dashboard
- Simple cookie-based password auth

Usage:
    DEXTER_WEB_PASSWORD=yourpass uvicorn dexter.api:app --host 0.0.0.0 --port 8080
"""

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dexter.engine import TradingEngine
from dexter.state import AgentStatus, SystemMode, RiskSnapshot, get_state
from models import TradeStatus


# Optional imports — wrapped so missing broker deps do not break the API
def _import_get_all_positions():
    from tools.execution import get_all_positions
    return get_all_positions


def _import_get_recent_trades():
    from tools.reporting_fixed import get_recent_trades
    return get_recent_trades


def _import_trade_counter():
    from tools.trade_counter import TradeCounter
    return TradeCounter


def _import_call_brain():
    from tools.brain import call_brain
    return call_brain


def _import_chat_persona():
    from tools.brain import DEXTER_CHAT_PERSONA_PROMPT
    return DEXTER_CHAT_PERSONA_PROMPT


def _import_orchestrator():
    from standalone.orchestrator import WorkflowOrchestrator
    return WorkflowOrchestrator


def _import_alpha_trader():
    from standalone.main import AlphaTrader
    return AlphaTrader


# ─── CONFIG ───

BASE_DIR = Path(__file__).parent.parent
WEB_DIR = BASE_DIR / "web"
DIST_DIR = WEB_DIR / "dist"

SESSION_NAME = "dexter_session"
SESSION_SECRET = os.getenv("DEXTER_WEB_PASSWORD", "")

# Global references
_engine: Optional[TradingEngine] = None
_orchestrator: Optional[Any] = None
_alpha_trader: Optional[Any] = None
_alpha_task: Optional[asyncio.Task] = None


# ─── LIFESPAN / BROADCAST LOOP ───

class ConnectionManager:
    """Tracks active WebSocket clients."""

    def __init__(self):
        self.active: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


async def _get_reports() -> List[Dict[str, Any]]:
    reports_dir = BASE_DIR / "data" / "reports"
    files = []
    if reports_dir.exists():
        for f in sorted(reports_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
            st = f.stat()
            files.append({"name": f.name, "mtime": st.st_mtime, "size": st.st_size})
    return files


async def _get_workflows() -> List[Dict[str, str]]:
    global _orchestrator
    try:
        if _orchestrator is None:
            _orchestrator = _import_orchestrator()(config={})
        await _orchestrator.initialize()
        return [{"id": wid, "name": wf.get("name", wid)} for wid, wf in _orchestrator.workflows.items()]
    except Exception:
        return []


def _active_venues_from_positions(positions: List[Dict]) -> List[str]:
    """Derive active venues from broker position data and configured credentials."""
    venues = {p.get("venue") for p in positions if p.get("venue")}
    if os.getenv("OANDA_API_KEY") and os.getenv("OANDA_ACCOUNT_ID"):
        venues.add("OANDA")
    if os.getenv("SCHWAB_APP_KEY") and os.getenv("SCHWAB_APP_SECRET"):
        venues.add("Schwab")
    if os.getenv("TOPSTEP_USERNAME") and os.getenv("TOPSTEP_PASSWORD"):
        venues.add("TopstepX")
    if os.getenv("KALSHI_API_KEY"):
        venues.add("Kalshi")
    return sorted(v for v in venues if v)


async def _load_merged_trades(limit: int = 100) -> List[Dict[str, Any]]:
    """Load real trades from audit DB and merge with in-memory state trades."""
    try:
        get_recent_trades = _import_get_recent_trades()
        audit_rows = await get_recent_trades(limit=limit)
    except Exception as e:
        get_state().add_log(f"Audit trade load failed: {e}")
        audit_rows = []

    seen_ids = set()
    trades = []

    for row in audit_rows:
        trade_id = str(row.get("id", ""))
        if not trade_id:
            continue
        seen_ids.add(trade_id)
        side = (row.get("side") or "").lower()
        direction_map = {
            "buy": "long",
            "buy_to_open": "long",
            "sell": "short",
            "sell_to_open": "short",
            "sell_to_close": "closed",
            "buy_to_close": "closed",
        }
        direction = direction_map.get(side, side)
        status = (row.get("status") or "filled").lower()
        if status in ("submitted", "pending"):
            status = "pending"
        trades.append({
            "id": trade_id,
            "timestamp": row.get("timestamp", ""),
            "symbol": row.get("symbol", ""),
            "direction": direction,
            "size": row.get("quantity"),
            "venue": row.get("venue", ""),
            "method": row.get("order_type") or "auto",
            "status": status,
            "pnl": row.get("pnl") or 0.0,
            "error": row.get("notes", ""),
        })

    # Merge any in-memory trades not yet persisted (e.g., pending intents)
    for t in get_state().trades:
        tid = str(t.id)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        trades.append({
            "id": tid,
            "timestamp": t.timestamp.isoformat() if t.timestamp else "",
            "symbol": t.symbol,
            "direction": t.direction,
            "size": t.size,
            "venue": t.venue,
            "method": t.method,
            "status": t.status,
            "pnl": t.pnl or 0.0,
            "error": t.error or "",
        })

    return trades


def _compute_pnl(trades: List[Dict[str, Any]], positions: List[Dict] = None) -> Dict[str, Any]:
    total = sum((t.get("pnl") or 0) for t in trades)
    if positions:
        total += sum(float(p.get("pnl") or 0) for p in positions)
    wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
    losses = sum(1 for t in trades if (t.get("pnl") or 0) < 0)
    return {
        "total_pnl": round(total, 2),
        "wins": wins,
        "losses": losses,
        "count": len(trades),
    }


def _build_agents() -> List[Dict[str, Any]]:
    """Build the unified agent list from state agents + scheduled jobs."""
    state = get_state()
    agents = [
        {
            "name": a.name,
            "status": a.status.value,
            "last_action": a.last_action,
            "last_updated": a.last_updated.isoformat() if a.last_updated else None,
            "error": a.error,
        }
        for a in state.agents.values()
    ]
    if _alpha_trader is not None and getattr(_alpha_trader, "scheduler", None):
        try:
            for job in _alpha_trader.scheduler.scheduler.get_jobs():
                next_run = job.next_run_time
                agents.append({
                    "name": job.id,
                    "status": "idle" if next_run else "busy",
                    "last_action": f"next run {next_run.isoformat() if next_run else 'N/A'}",
                    "last_updated": datetime.utcnow().isoformat(),
                    "error": None,
                })
        except Exception:
            pass
    return agents


async def build_state_payload() -> Dict[str, Any]:
    """Build the full state snapshot sent over WebSocket from real data sources."""
    global _alpha_trader
    state = get_state()
    state.tick_uptime()

    positions_data: Dict[str, Any] = {
        "positions": [],
        "total_value": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        get_all_positions = _import_get_all_positions()
        positions_data = await get_all_positions()
    except Exception as e:
        positions_data["error"] = str(e)
        state.add_log(f"Position fetch error: {e}")

    active_venues = _active_venues_from_positions(positions_data.get("positions", []))
    state.active_venues = active_venues

    open_state = [t for t in state.trades if t.status not in ("closed", "cancelled")]
    positions_data["state_trades"] = [
        {
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "size": t.size,
            "venue": t.venue,
            "method": t.method,
            "status": t.status,
            "timestamp": t.timestamp.isoformat() if t.timestamp else "",
            "pnl": t.pnl,
            "error": t.error,
        }
        for t in open_state
    ]

    pending = []
    if _engine is not None:
        pending = [i.to_dict() for i in _engine.get_pending_intents()]

    trades = await _load_merged_trades(limit=100)
    pnl = _compute_pnl(trades, positions_data.get("positions"))

    # Build agent list: static agents from state + scheduled jobs from the real scheduler
    agents = _build_agents()

    # Risk snapshot from trade counter + configured limits
    risk = state.risk
    try:
        counter = _import_trade_counter()()
        daily_trades = {
            v: counter.get_count(v)
            for v in ["oanda", "schwab", "topstep", "apex", "kalshi"]
        }
        daily_limits = {v: counter.get_max_trades(v) for v in daily_trades}
        rate_limited = {v: not counter.can_trade(v) for v in daily_trades}
        risk = RiskSnapshot(
            circuit_breaker_active=state.risk.circuit_breaker_active,
            daily_trades=daily_trades,
            daily_limits=daily_limits,
            rate_limited=rate_limited,
            consecutive_losses=state.risk.consecutive_losses,
        )
        state.update_risk(risk)
    except Exception as e:
        state.add_log(f"Risk snapshot error: {e}")

    return {
        "type": "state",
        "status": {
            "mode": state.mode.value,
            "dry_run": state.dry_run,
            "uptime_seconds": state.uptime_seconds,
            "active_venues": active_venues,
            "agent_count": len(agents),
            "trade_count": len(trades),
        },
        "trades": trades,
        "agents": agents,
        "risk": {
            "circuit_breaker_active": risk.circuit_breaker_active,
            "daily_trades": risk.daily_trades,
            "daily_limits": risk.daily_limits,
            "rate_limited": risk.rate_limited,
            "consecutive_losses": risk.consecutive_losses,
        },
        "positions": positions_data,
        "pending": pending,
        "pnl": pnl,
        "reports": await _get_reports(),
        "workflows": await _get_workflows(),
        "logs": state.logs[-200:],
    }


async def broadcast_loop():
    """Periodically push state to all connected WebSocket clients."""
    while True:
        await asyncio.sleep(2)
        if not manager.active:
            continue
        try:
            payload = await build_state_payload()
            await manager.broadcast(payload)
        except Exception as e:
            get_state().add_log(f"Broadcast loop error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(broadcast_loop())

    # Auto-start AlphaTrader if configured (consolidated daemon mode)
    auto_start = os.getenv("ALPHA_TRADER_AUTO_START", "").lower() == "true"
    if auto_start:
        try:
            await _perform_control("start")
            get_state().add_log("Alpha Trader auto-started on API server startup")
        except Exception as e:
            get_state().add_log(f"Alpha Trader auto-start failed: {e}")

    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Alpha Trader API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── AUTH ───

def _sign(value: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


def create_session() -> str:
    return _sign("dexter_session")


def verify_session(token: Optional[str]) -> bool:
    if not SESSION_SECRET or not token:
        return False
    return hmac.compare_digest(token, create_session())


async def require_auth(request: Request):
    token = request.cookies.get(SESSION_NAME)
    if not verify_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ─── MODELS ───

class StatusResponse(BaseModel):
    mode: str
    dry_run: bool
    uptime_seconds: float
    active_venues: List[str]
    agent_count: int
    trade_count: int


class TradeResponse(BaseModel):
    id: str
    symbol: str
    direction: str
    size: Optional[int]
    venue: str
    method: str
    status: str
    timestamp: str
    pnl: Optional[float]
    error: Optional[str]


class AgentResponse(BaseModel):
    name: str
    status: str
    last_action: str
    last_updated: Optional[str]
    error: Optional[str]


class RiskResponse(BaseModel):
    circuit_breaker_active: bool
    daily_trades: dict
    daily_limits: dict
    rate_limited: dict
    consecutive_losses: int


class ManualTradeRequest(BaseModel):
    symbol: str
    direction: str = "long"
    size: int = 1
    venue: str = "oanda"


class LoginRequest(BaseModel):
    password: str


class ChatRequest(BaseModel):
    message: str


class SettingsRequest(BaseModel):
    settings: Dict[str, str]



# ─── STATIC FILES ───
# Static mount is added at the end of the file so API routes are matched first.


# ─── AUTH ENDPOINTS ───

@app.get("/api/me")
async def me(request: Request):
    token = request.cookies.get(SESSION_NAME)
    return {"authenticated": verify_session(token)}


@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    if not SESSION_SECRET:
        raise HTTPException(status_code=500, detail="Web password not configured")
    if not hmac.compare_digest(req.password, SESSION_SECRET):
        raise HTTPException(status_code=401, detail="Invalid password")
    response.set_cookie(
        SESSION_NAME,
        create_session(),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return {"status": "ok"}


@app.post("/api/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_NAME)
    return {"status": "ok"}


# ─── WEBSOCKET ───

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.cookies.get(SESSION_NAME)
    if not verify_session(token):
        await websocket.close(code=1008)
        return

    await manager.connect(websocket)
    try:
        await websocket.send_json(await build_state_payload())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ─── API ENDPOINTS (protected) ───

@app.get("/api/status", response_model=StatusResponse)
async def status(_=Depends(require_auth)):
    state = get_state()
    state.tick_uptime()
    trades = await _load_merged_trades(limit=1000)
    agents = _build_agents()
    return StatusResponse(
        mode=state.mode.value,
        dry_run=state.dry_run,
        uptime_seconds=state.uptime_seconds,
        active_venues=state.active_venues,
        agent_count=len(agents),
        trade_count=len(trades),
    )


@app.get("/api/trades", response_model=List[TradeResponse])
async def trades(limit: int = 50, _=Depends(require_auth)):
    trades = await _load_merged_trades(limit=limit)
    result = []
    for t in trades[:limit]:
        result.append(
            TradeResponse(
                id=t["id"],
                symbol=t["symbol"],
                direction=t["direction"],
                size=t["size"],
                venue=t["venue"],
                method=t["method"],
                status=t["status"],
                timestamp=t["timestamp"],
                pnl=t["pnl"],
                error=t["error"],
            )
        )
    return result


@app.get("/api/agents", response_model=List[AgentResponse])
async def agents(_=Depends(require_auth)):
    return [
        AgentResponse(
            name=a["name"],
            status=a["status"],
            last_action=a["last_action"],
            last_updated=a["last_updated"],
            error=a["error"],
        )
        for a in _build_agents()
    ]


@app.get("/api/risk", response_model=RiskResponse)
async def risk(_=Depends(require_auth)):
    state = get_state()
    r = state.risk
    return RiskResponse(
        circuit_breaker_active=r.circuit_breaker_active,
        daily_trades=r.daily_trades,
        daily_limits=r.daily_limits,
        rate_limited=r.rate_limited,
        consecutive_losses=r.consecutive_losses,
    )


@app.get("/api/positions")
async def positions(_=Depends(require_auth)):
    state = get_state()
    result: Dict[str, Any] = {
        "positions": [],
        "total_value": 0.0,
        "timestamp": datetime.utcnow().isoformat(),
    }
    try:
        get_all_positions = _import_get_all_positions()
        result = await get_all_positions()
    except Exception as e:
        result["error"] = str(e)
        state.add_log(f"Position fetch error: {e}")

    open_state = [t for t in state.trades if t.status not in ("closed", "cancelled")]
    result["state_trades"] = [
        {
            "id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "size": t.size,
            "venue": t.venue,
            "method": t.method,
            "status": t.status,
            "timestamp": t.timestamp.isoformat() if t.timestamp else "",
            "pnl": t.pnl,
            "error": t.error,
        }
        for t in open_state
    ]
    return result


@app.get("/api/pending")
async def pending(_=Depends(require_auth)):
    global _engine
    if _engine is None:
        return []
    return [i.to_dict() for i in _engine.get_pending_intents()]


@app.post("/api/approve/{intent_id}")
async def approve_intent(intent_id: str, _=Depends(require_auth)):
    global _engine
    if _engine is None:
        return {"status": "no_engine"}
    ok = await _engine.approve_intent(intent_id)
    return {"status": "approved" if ok else "not_found"}


@app.post("/api/reject/{intent_id}")
async def reject_intent(intent_id: str, _=Depends(require_auth)):
    global _engine
    if _engine is None:
        return {"status": "no_engine"}
    ok = _engine.reject_intent(intent_id)
    return {"status": "rejected" if ok else "not_found"}


@app.get("/api/pnl")
async def pnl(_=Depends(require_auth)):
    trades = await _load_merged_trades(limit=1000)
    return _compute_pnl(trades)


@app.get("/api/reports")
async def reports(_=Depends(require_auth)):
    return await _get_reports()


@app.get("/api/reports/{report_name}")
async def report_content(report_name: str, _=Depends(require_auth)):
    reports_dir = BASE_DIR / "data" / "reports"
    safe_name = Path(report_name).name
    path = reports_dir / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read report: {e}")
    return {"name": safe_name, "content": content}


@app.get("/api/workflows")
async def workflows(_=Depends(require_auth)):
    return await _get_workflows()


@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str, _=Depends(require_auth)):
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = _import_orchestrator()(config={})
    await _orchestrator.initialize()
    if workflow_id not in _orchestrator.workflows:
        raise HTTPException(status_code=404, detail="Unknown workflow")

    async def _run():
        try:
            result = await _orchestrator.execute_workflow(workflow_id)
            get_state().add_log(f"Workflow {workflow_id} finished: {result.status}")
        except Exception as e:
            get_state().add_log(f"Workflow {workflow_id} failed: {e}")

    asyncio.create_task(_run())
    return {"status": "started", "workflow_id": workflow_id}


@app.post("/api/trades")
async def create_trade(req: ManualTradeRequest, _=Depends(require_auth)):
    global _engine
    state = get_state()

    if _engine is None:
        _engine = TradingEngine(dry_run=state.dry_run)

    intent_id = await _engine.place_manual_trade(req.symbol, req.direction, req.size, req.venue)

    # Auto-execute venues that are configured for AUTO mode; leave Schwab/confirm venues pending
    auto_venues = {"oanda", "kalshi", "polymarket", "topstep"}
    if req.venue.lower() in auto_venues:
        await _engine.approve_intent(intent_id)
        return {"status": "executed", "symbol": req.symbol, "intent_id": intent_id}

    return {"status": "pending", "symbol": req.symbol, "intent_id": intent_id}


async def _start_alpha_trader_task():
    """Background task that owns the AlphaTrader lifecycle."""
    global _alpha_trader
    try:
        await _alpha_trader.start()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        get_state().add_log(f"AlphaTrader task error: {e}")


async def _perform_control(action: str):
    """Execute a control action without auth checks."""
    global _alpha_trader, _alpha_task, _engine
    state = get_state()

    if action == "start":
        if _alpha_trader is None or not getattr(_alpha_trader, "running", False):
            config_path = BASE_DIR / "config" / "config.yaml"
            AlphaTrader = _import_alpha_trader()
            _alpha_trader = AlphaTrader(config_path=config_path)
            _alpha_task = asyncio.create_task(_start_alpha_trader_task())
            state.dry_run = os.getenv("ALPHA_TRADER_DRY_RUN", "true").lower() != "false"
            state.add_log("Alpha Trader scheduler starting via dashboard...")
        else:
            if _alpha_trader.scheduler:
                _alpha_trader.scheduler.scheduler.resume()
            state.set_mode(SystemMode.RUNNING)
            state.add_log("Alpha Trader scheduler resumed via API")
        return {"status": "started"}

    elif action == "pause":
        if _alpha_trader and getattr(_alpha_trader, "scheduler", None):
            _alpha_trader.scheduler.scheduler.pause()
        state.set_mode(SystemMode.PAUSED)
        state.add_log("Alpha Trader scheduler paused via API")
        return {"status": "paused"}

    elif action == "stop":
        if _alpha_trader:
            await _alpha_trader.stop()
            _alpha_trader = None
        if _alpha_task:
            _alpha_task.cancel()
            try:
                await _alpha_task
            except asyncio.CancelledError:
                pass
            _alpha_task = None
        if _engine:
            await _engine.stop()
            _engine = None
        state.set_mode(SystemMode.STOPPED)
        state.active_venues = []
        state.add_log("Alpha Trader scheduler stopped via API")
        return {"status": "stopped"}

    return {"error": f"Unknown action: {action}"}


@app.post("/api/control/{action}")
async def control(action: str, _=Depends(require_auth)):
    return await _perform_control(action)


@app.post("/api/service/restart")
async def service_restart(_=Depends(require_auth)):
    """Restart the system service (launchd/systemd) that owns this API server."""
    import platform
    import subprocess

    system = platform.system()
    project_dir = Path(__file__).parent.parent

    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "com.allternit.alpha-trader.plist"
        if not plist_path.exists():
            raise HTTPException(status_code=500, detail="Launchd plist not found")
        cmd = f"sleep 2; launchctl unload {plist_path}; launchctl load {plist_path}"
    elif system == "Linux":
        cmd = "sleep 2; sudo systemctl restart alpha-trader"
    else:
        raise HTTPException(status_code=500, detail=f"Service restart not supported on {system}")

    # Detach the restart command so it survives this process being killed
    subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    get_state().add_log("Service restart initiated — dashboard will reconnect shortly...")
    return {"status": "restarting", "system": system}


@app.get("/api/service/status")
async def service_status(_=Depends(require_auth)):
    """Check whether the system service is loaded/running."""
    import platform
    import subprocess

    system = platform.system()
    running = False
    detail = "unknown"

    try:
        if system == "Darwin":
            plist_label = "com.allternit.alpha-trader"
            result = subprocess.run(
                ["launchctl", "list", plist_label],
                capture_output=True, text=True, timeout=5
            )
            running = result.returncode == 0 and plist_label in result.stdout
            detail = "loaded" if running else "not loaded"
        elif system == "Linux":
            result = subprocess.run(
                ["systemctl", "is-active", "alpha-trader"],
                capture_output=True, text=True, timeout=5
            )
            running = result.returncode == 0 and "active" in result.stdout
            detail = result.stdout.strip()
    except Exception as e:
        detail = f"error: {e}"

    return {"system": system, "running": running, "detail": detail}


@app.get("/api/logs/stream")
async def log_stream(_=Depends(require_auth)):
    """Legacy SSE endpoint for live log streaming."""
    state = get_state()
    queue = state.subscribe()

    async def event_generator():
        try:
            while True:
                line = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {json.dumps({'log': line})}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'heartbeat': True})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            state.unsubscribe(queue)

    return Response(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/chat")
async def chat(req: ChatRequest, _=Depends(require_auth)):
    text = await handle_chat(req.message)
    return {"text": text, "response": text}


@app.get("/api/settings")
async def get_settings(_=Depends(require_auth)):
    env_path = BASE_DIR / ".env"
    settings = {}
    keys_of_interest = [
        "DEXTER_WEB_PASSWORD",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "LLM_PROVIDER",
        "BROWSER_USE_MODEL",
        "SCHWAB_APP_KEY",
        "SCHWAB_APP_SECRET",
        "SCHWAB_REDIRECT_URI",
        "OANDA_API_KEY",
        "OANDA_ACCOUNT_ID",
        "KALSHI_API_KEY",
        "KALSHI_API_SECRET",
        "TOPSTEP_USERNAME",
        "TOPSTEP_PASSWORD"
    ]
    from dotenv import dotenv_values
    file_vals = {}
    if env_path.exists():
        try:
            file_vals = dotenv_values(env_path)
        except Exception:
            pass
    for k in keys_of_interest:
        val = file_vals.get(k) or os.getenv(k, "")
        settings[k] = val
    return {"settings": settings}


@app.post("/api/settings")
async def save_settings(req: SettingsRequest, _=Depends(require_auth)):
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r") as f:
            lines = f.readlines()
    key_line_map = {}
    for idx, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("#") and "=" in line_stripped:
            parts = line_stripped.split("=", 1)
            key_line_map[parts[0].strip()] = idx
    for k, v in req.settings.items():
        clean_v = v.strip()
        if " " in clean_v or "#" in clean_v:
            # Quote if contains spaces or hash
            if not ((clean_v.startswith('"') and clean_v.endswith('"')) or (clean_v.startswith("'") and clean_v.endswith("'"))):
                clean_v = f'"{clean_v}"'
        line_content = f"{k}={clean_v}\n"
        if k in key_line_map:
            lines[key_line_map[k]] = line_content
        else:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(line_content)
    with open(env_path, "w") as f:
        f.writelines(lines)
    from dotenv import load_dotenv
    load_dotenv(env_path, override=True)
    global SESSION_SECRET
    if "DEXTER_WEB_PASSWORD" in req.settings and req.settings["DEXTER_WEB_PASSWORD"]:
        SESSION_SECRET = req.settings["DEXTER_WEB_PASSWORD"]
    return {"status": "success", "message": "Settings saved successfully."}



# ─── CHAT HANDLER ───

def _format_duration(seconds: float) -> str:
    if not seconds:
        return "0s"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


async def handle_chat(message: str) -> str:
    global _engine, _orchestrator, _alpha_trader, _alpha_task
    state = get_state()
    text = message.strip().lower()

    # Build one live payload so commands and AI context reflect real dashboard data.
    payload = await build_state_payload()
    status = payload["status"]
    trades = payload.get("trades", [])
    agents = payload.get("agents", [])
    positions = payload.get("positions", {}).get("positions", [])
    risk = payload.get("risk", {})
    pnl = payload.get("pnl", {})

    if text in ("status", "state"):
        return (
            f"Mode: {status.get('mode')} | dry_run: {status.get('dry_run')} | "
            f"uptime: {_format_duration(status.get('uptime_seconds', 0))} | "
            f"trades: {status.get('trade_count', 0)} | agents: {status.get('agent_count', 0)} | "
            f"positions: {len(positions)} | venues: {', '.join(status.get('active_venues', [])) or 'none'}"
        )

    if text in ("trades", "orders"):
        if not trades:
            return "No trades recorded yet."
        lines = [f"{t.get('symbol')} {t.get('direction')} x{t.get('size')} @ {t.get('venue')} — {t.get('status')}" for t in trades[:10]]
        return "Recent trades:\n" + "\n".join(lines)

    if text in ("agents", "bots"):
        if not agents:
            return "No agents registered."
        lines = [f"{a.get('name')}: {a.get('status')}" for a in agents]
        return "Agents:\n" + "\n".join(lines)

    if text == "risk":
        return (
            f"Circuit breaker: {'ACTIVE' if risk.get('circuit_breaker_active') else 'OK'}\n"
            f"Consecutive losses: {risk.get('consecutive_losses', 0)}\n"
            f"Daily trades: {risk.get('daily_trades', {})}\n"
            f"Rate limited: {risk.get('rate_limited', {})}"
        )

    if text in ("positions", "pos"):
        if not positions:
            return "No open positions."
        lines = [f"{p.get('symbol')} {p.get('side')} x{p.get('size')} @ {p.get('venue')} — ${p.get('pnl', 0):.2f}" for p in positions[:10]]
        return "Positions:\n" + "\n".join(lines)

    if text in ("pnl", "profit", "loss"):
        return (
            f"Realized P&L: ${pnl.get('realized', 0):.2f}\n"
            f"Unrealized P&L: ${pnl.get('unrealized', 0):.2f}\n"
            f"Total P&L: ${pnl.get('total', 0):.2f}"
        )

    if text in ("start", "resume", "go"):
        if _alpha_trader is None or not getattr(_alpha_trader, "running", False):
            config_path = BASE_DIR / "config" / "config.yaml"
            AlphaTrader = _import_alpha_trader()
            _alpha_trader = AlphaTrader(config_path=config_path)
            _alpha_task = asyncio.create_task(_start_alpha_trader_task())
            state.dry_run = os.getenv("ALPHA_TRADER_DRY_RUN", "true").lower() != "false"
            return "Alpha Trader scheduler starting via chat..."
        if _alpha_trader and getattr(_alpha_trader, "scheduler", None):
            _alpha_trader.scheduler.scheduler.resume()
        state.set_mode(SystemMode.RUNNING)
        state.add_log("Alpha Trader scheduler resumed via chat")
        return "Scheduler resumed."

    if text == "pause":
        state.set_mode(SystemMode.PAUSED)
        state.add_log("Engine paused via chat")
        return "Engine paused."

    if text == "stop":
        if _alpha_trader or _engine:
            if _alpha_trader:
                await _alpha_trader.stop()
                _alpha_trader = None
            if _alpha_task:
                _alpha_task.cancel()
                try:
                    await _alpha_task
                except asyncio.CancelledError:
                    pass
                _alpha_task = None
            if _engine:
                await _engine.stop()
                _engine = None
            state.set_mode(SystemMode.STOPPED)
            state.active_venues = []
            return "Alpha Trader scheduler stopped."
        return "Scheduler is not running."

    if text.startswith("approve "):
        intent_id = text.split()[1]
        if _engine and await _engine.approve_intent(intent_id):
            return f"Approved and executing {intent_id}."
        return "Intent not found or engine not running."

    if text.startswith("reject "):
        intent_id = text.split()[1]
        if _engine and _engine.reject_intent(intent_id):
            return f"Rejected {intent_id}."
        return "Intent not found or engine not running."

    if text.startswith("trade "):
        parts = message.split()
        if len(parts) < 4:
            return "Usage: trade SYMBOL long|short SIZE [VENUE]"
        symbol, direction, size = parts[1], parts[2], int(parts[3])
        venue = parts[4] if len(parts) > 4 else "oanda"
        if _engine is None:
            return "Engine not running. Start it first."
        await _engine.place_manual_trade(symbol, direction, size, venue)
        return f"Submitted {symbol} {direction} x{size} @ {venue}."

    if text.startswith("run workflow ") or text.startswith("run "):
        wf_id = text.replace("run workflow ", "").replace("run ", "").strip()
        if _orchestrator is None:
            _orchestrator = _import_orchestrator()(config={})
        await _orchestrator.initialize()
        if wf_id not in _orchestrator.workflows:
            available = ", ".join(_orchestrator.workflows.keys())
            return f"Unknown workflow: {wf_id}. Available: {available}"
        asyncio.create_task(_orchestrator.execute_workflow(wf_id))
        return f"Started workflow {wf_id}."

    if text in ("help", "commands"):
        return (
            "Available commands:\n"
            "status, trades, agents, risk, positions, start, pause, stop\n"
            "approve INTENT_ID, reject INTENT_ID\n"
            "trade SYMBOL long|short SIZE [VENUE]\n"
            "run WORKFLOW_ID\n"
            "Or ask me anything about the market."
        )

    try:
        call_brain = _import_call_brain()
        persona = _import_chat_persona()

        # Build live context for the AI from the same payload the dashboard uses.
        recent_trades = trades[:5]
        open_positions = [p for p in positions if p.get("size", 0)]
        trade_lines = [
            f"{t.get('symbol')} {t.get('direction')} x{t.get('size')} @ {t.get('venue')} ({t.get('status')})"
            for t in recent_trades
        ]
        context = (
            f"Alpha Trader status: mode={status.get('mode')}, dry_run={status.get('dry_run')}, "
            f"uptime={_format_duration(status.get('uptime_seconds', 0))}, active_venues={status.get('active_venues')}\n"
            f"Open positions: {len(open_positions)} | Total position value: ${sum(p.get('market_value', 0) for p in open_positions):.2f}\n"
            f"Recent trades: {trade_lines}\n"
            f"Agents online: {sum(1 for a in agents if a.get('status') in ('idle', 'busy'))}/{len(agents)}\n"
            f"P&L: realized=${pnl.get('realized', 0):.2f}, unrealized=${pnl.get('unrealized', 0):.2f}, total=${pnl.get('total', 0):.2f}\n"
            f"Risk: circuit_breaker={risk.get('circuit_breaker_active')}, daily_trades={risk.get('daily_trades')}, "
            f"consecutive_losses={risk.get('consecutive_losses', 0)}\n"
        )

        answer = await call_brain(
            prompt=f"{context}\nUser asked: {message}",
            system_instruction=persona,
        )
        if answer and answer.strip():
            return answer
        return (
            "Dexter's AI brain is offline: no working LLM provider. "
            "Set KIMI_API_KEY in .env for the Kimi API, or authorize this device with `kimi-cli login`."
        )
    except Exception as e:
        return f"Brain error: {e}"


# ─── STATIC FILE MOUNT + SPA ROUTES ───
# Register explicit client-side routes so refresh/deep-linking works.
# StaticFiles is mounted last to serve assets and the root index.html.

_SPA_ROUTES = ["/", "/dashboard", "/trades", "/positions", "/pending", "/chat", "/logs", "/reports", "/control", "/settings"]

if DIST_DIR.exists():
    _index_html = (DIST_DIR / "index.html").read_text()

    def _make_spa_handler(html: str):
        async def handler():
            return HTMLResponse(content=html)
        return handler

    for _route in _SPA_ROUTES:
        app.get(_route, response_class=HTMLResponse)(_make_spa_handler(_index_html))

    # Static assets and root fallback
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="static")
else:
    @app.get("/", response_class=HTMLResponse)
    async def root_dev():
        return (
            "<html><body style='font-family:sans-serif;padding:40px'>"
            "<h1>Alpha Trader API</h1>"
            "<p>Frontend not built. Run <code>cd web && npm run build</code>.</p>"
            "</body></html>"
        )
