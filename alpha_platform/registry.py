"""Discover and report the four forked components plus Dexter."""

from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from alpha_platform.paths import AGENT_ROOT, forks

DATA = AGENT_ROOT / "data"

# US names Massive can quote. Venue cards still carry FX/futures symbols.
DESK_WATCHLIST = [
    "SPY",
    "QQQ",
    "AAPL",
    "NVDA",
    "MSFT",
    "AMZN",
    "META",
    "TSLA",
    "GLD",
    "TLT",
]

_CHART_ALIASES = {
    "EURUSD": "SPY",
    "GBPUSD": "SPY",
    "USDJPY": "SPY",
    "AUDUSD": "SPY",
    "XAUUSD": "GLD",
    "NQ": "QQQ",
    "NAS100": "QQQ",
    "BTCUSD": "IBIT",
    "BTCUSDT": "IBIT",
    "BTC": "IBIT",
    "ETHUSD": "ETH",
    "ETHUSDT": "ETH",
    "SOLUSD": "SOL",
    "SOLUSDT": "SOL",
}


def desk_watchlist() -> List[str]:
    return list(DESK_WATCHLIST)


def chart_symbol_for(symbol: str) -> str:
    raw = (symbol or "SPY").upper().replace("/", "").replace("-", "")
    if raw.endswith("USDT") and raw[:-4] in {"BTC", "ETH", "SOL"}:
        raw = raw[:-4] + "USD"
    return _CHART_ALIASES.get(raw, raw or "SPY")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _paper_trades(limit: int = 25) -> List[Dict[str, str]]:
    path = DATA / "paper_trades.csv"
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-max(1, limit) :]


def _signals(limit: int = 25) -> List[Dict[str, Any]]:
    rows = _read_json(DATA / "signals" / "signals.json", [])
    if not isinstance(rows, list):
        return []
    return rows[-max(1, limit) :]


def _env_on(*names: str) -> bool:
    return all(bool(os.getenv(n, "").strip()) for n in names)


VENUE_BOOK = [
    {
        "id": "oanda",
        "name": "OANDA",
        "cls": "FX / metals",
        "symbol": "EURUSD",
        "execute": True,
        "connected": lambda: _env_on("OANDA_API_KEY", "OANDA_ACCOUNT_ID"),
    },
    {
        "id": "schwab",
        "name": "Schwab",
        "cls": "US equities / options",
        "symbol": "SPY",
        "execute": True,
        "connected": lambda: _env_on("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"),
    },
    {
        "id": "topstep",
        "name": "TopstepX",
        "cls": "Futures",
        "symbol": "NQ",
        "execute": True,
        "connected": lambda: _env_on("PROJECT_X_API_KEY", "PROJECT_X_USERNAME"),
    },
    {
        "id": "kalshi",
        "name": "Kalshi",
        "cls": "Event contracts",
        "symbol": "KXBTCD",
        "execute": True,
        "connected": lambda: _env_on("KALSHI_API_KEY"),
    },
    {
        "id": "polymarket",
        "name": "Polymarket",
        "cls": "Prediction markets",
        "symbol": "BTC",
        "execute": True,
        "connected": lambda: _env_on("POLYMARKET_API_KEY"),
    },
    {
        "id": "crypto",
        "name": "Crypto",
        "cls": "Spot / perp (CCXT)",
        "symbol": "BTCUSD",
        "execute": True,
        "connected": lambda: _env_on("CRYPTO_API_KEY"),
    },
    {
        "id": "massive",
        "name": "Massive",
        "cls": "Market data",
        "symbol": "SPY",
        "execute": False,
        "connected": lambda: _env_on("MASSIVE_API_KEY"),
    },
    {
        "id": "hummingbot",
        "name": "Hummingbot",
        "cls": "HFT crypto bots",
        "symbol": "BTCUSDT",
        "execute": False,
        "connected": lambda: forks().hummingbot.exists(),
    },
    {
        "id": "autohedge",
        "name": "AutoHedge",
        "cls": "Swarm director",
        "symbol": "AAPL",
        "execute": False,
        "connected": lambda: forks().autohedge.exists(),
    },
    {
        "id": "vibe",
        "name": "Vibe-Trading",
        "cls": "Research / alpha zoo",
        "symbol": "SPY",
        "execute": False,
        "connected": lambda: forks().vibe.exists(),
    },
    {
        "id": "paper",
        "name": "Paper",
        "cls": "Simulated fills",
        "symbol": "SPY",
        "execute": True,
        "connected": lambda: True,
    },
    {
        "id": "tradovate",
        "name": "Tradovate",
        "cls": "Futures",
        "symbol": "NQ",
        "execute": True,
        "connected": lambda: _env_on("TRADOVATE_USERNAME", "TRADOVATE_PASSWORD"),
    },
    {
        "id": "apex",
        "name": "Apex",
        "cls": "Prop futures",
        "symbol": "ES",
        "execute": True,
        "connected": lambda: _env_on("APEX_USERNAME", "APEX_PASSWORD") or _env_on("TRADOVATE_USERNAME"),
    },
    {
        "id": "interactive_brokers",
        "name": "IBKR",
        "cls": "Equities / futures",
        "symbol": "SPY",
        "execute": True,
        "connected": lambda: _env_on("IB_HOST") or _env_on("IBKR_ACCOUNT"),
    },
]


def _venues() -> Dict[str, bool]:
    return {v["id"]: bool(v["connected"]()) for v in VENUE_BOOK}


def venue_cards() -> List[Dict[str, Any]]:
    return [
        {
            "id": v["id"],
            "name": v["name"],
            "cls": v["cls"],
            "symbol": v["symbol"],
            "execute": v["execute"],
            "connected": bool(v["connected"]()),
        }
        for v in VENUE_BOOK
    ]


def _py_modules(root: Path, rel: str) -> List[Dict[str, str]]:
    base = root / rel
    if not base.exists():
        return []
    items: List[Dict[str, str]] = []
    for path in sorted(base.rglob("*.py")):
        if path.name.startswith("__"):
            continue
        items.append(
            {
                "id": path.stem,
                "path": str(path.relative_to(root)),
                "group": path.parent.name,
            }
        )
    return items


def _skill_dirs(root: Path) -> List[Dict[str, str]]:
    skills = root / "agent" / "src" / "skills"
    if not skills.exists():
        return []
    out: List[Dict[str, str]] = []
    for d in sorted(p for p in skills.iterdir() if p.is_dir()):
        skill_md = d / "SKILL.md"
        out.append(
            {
                "id": d.name,
                "path": str(d.relative_to(root)),
                "has_skill_md": skill_md.exists(),
            }
        )
    return out


def hummingbot_inventory() -> Dict[str, Any]:
    hb = forks().hummingbot
    controllers = _py_modules(hb, "controllers")
    scripts = _py_modules(hb, "scripts")
    hbot_bin = hb / "bin" / "hbot"
    return {
        "root": str(hb) if hb.exists() else None,
        "present": hb.exists(),
        "hbot_bin": str(hbot_bin) if hbot_bin.exists() else None,
        "hbot_on_path": bool(shutil.which("hbot")),
        "controllers": controllers,
        "scripts": scripts,
        "controller_count": len(controllers),
        "script_count": len(scripts),
        "live_ready": False,
        "note": "Hummingbot needs its conda env + compiled Cython extensions before a bot can start. Catalog is live now. Live start is opt-in and disabled.",
    }


def vibe_inventory() -> Dict[str, Any]:
    vibe = forks().vibe
    skills = _skill_dirs(vibe)
    factors_dir = vibe / "agent" / "src" / "factors"
    factor_count = 0
    if factors_dir.exists():
        factor_count = sum(1 for p in factors_dir.rglob("*.py") if p.name != "__init__.py")
    return {
        "root": str(vibe) if vibe.exists() else None,
        "present": vibe.exists(),
        "skills": skills[:80],
        "skill_count": len(skills),
        "factor_count": factor_count,
        "frontend": str(vibe / "frontend") if (vibe / "frontend").exists() else None,
        "mcp_entry": "agent/mcp_server.py",
        "note": "Vibe-Trading is attached as a research sidecar. Skills/factors are catalogued from the fork. Full agent runtime needs vibe-trading-ai deps.",
    }


def autohedge_inventory() -> Dict[str, Any]:
    from alpha_platform.paths import ensure_autohedge_on_path

    ah = forks().autohedge
    importable = False
    reason = None
    if ah.exists():
        ensure_autohedge_on_path()
        try:
            import autohedge  # noqa: F401

            importable = True
        except Exception as exc:  # pragma: no cover - depends on swarms
            reason = str(exc)
    return {
        "root": str(ah) if ah.exists() else None,
        "present": ah.exists(),
        "importable": importable,
        "import_error": reason,
        "director": (ah / "autohedge" / "workers.py").exists() if ah.exists() else False,
        "note": "AutoHedge swarm (director → quant → risk → execution) is wired through Dexter. Live venue writes stay behind Alpha Trader risk gates.",
    }


def fincept_inventory() -> Dict[str, Any]:
    f = forks()
    app = f.fincept_app
    src = f.fincept_src
    running = False
    try:
        import subprocess

        proc = subprocess.run(
            ["pgrep", "-f", "FinceptTerminal"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        running = proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        running = False
    python = f.agent / "venv" / "bin" / "python"
    mcp_script = f.agent / "tools" / "alpha_trader_mcp_server.py"
    return {
        "app": str(app) if app.exists() else None,
        "app_present": app.exists(),
        "source": str(src) if src.exists() else None,
        "source_present": src.exists(),
        "running": running,
        "license": "AGPL-3.0 — keep separate from this MIT tree; attach over MCP",
        "mcp": {
            "name": "Alpha Trader",
            "command": str(python if python.exists() else "python"),
            "args": [str(mcp_script)],
        },
    }


def dexter_inventory() -> Dict[str, Any]:
    agent = forks().agent
    return {
        "root": str(agent),
        "present": True,
        "dry_run": os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"},
        "topstep_trading_enabled": os.getenv("TOPSTEP_TRADING_ENABLED", "false"),
        "dashboard": "python cli.py dashboard --dev",
        "mcp": "python cli.py mcp serve",
    }


def component_status() -> Dict[str, Any]:
    fincept = fincept_inventory()
    hb = hummingbot_inventory()
    vibe = vibe_inventory()
    ah = autohedge_inventory()
    dexter = dexter_inventory()
    components = [
        {
            "id": "dexter",
            "name": "Dexter (Alpha Trader)",
            "role": "brain / risk / brokers",
            "ok": True,
            "detail": dexter,
        },
        {
            "id": "fincept",
            "name": "Fincept Terminal",
            "role": "desktop terminal UI",
            "ok": bool(fincept.get("app_present")),
            "detail": fincept,
        },
        {
            "id": "hummingbot",
            "name": "Hummingbot",
            "role": "crypto executors / connectors",
            "ok": bool(hb.get("present")),
            "detail": hb,
        },
        {
            "id": "vibe",
            "name": "Vibe-Trading",
            "role": "research / alpha zoo / backtests",
            "ok": bool(vibe.get("present")),
            "detail": vibe,
        },
        {
            "id": "autohedge",
            "name": "AutoHedge",
            "role": "swarm director pipeline",
            "ok": bool(ah.get("present")),
            "detail": ah,
        },
    ]
    return {
        "ok": all(c["ok"] for c in components),
        "workspace": str(forks().agent.parent),
        "components": components,
    }


def inventory() -> Dict[str, Any]:
    status = component_status()
    hb = hummingbot_inventory()
    vibe = vibe_inventory()
    return {
        **status,
        "hummingbot_controllers": hb.get("controllers", []),
        "hummingbot_scripts": hb.get("scripts", []),
        "vibe_skills": vibe.get("skills", []),
        "vibe_skill_count": vibe.get("skill_count", 0),
        "vibe_factor_count": vibe.get("factor_count", 0),
    }


def desk_payload() -> Dict[str, Any]:
    """Single payload for the native Alpha Trader desk."""
    status = component_status()
    hb = hummingbot_inventory()
    vibe = vibe_inventory()
    breaker = _read_json(DATA / "circuit_breaker_state.json", {})
    backtest = _read_json(DATA / "backtest_focus_result.json", {})
    return {
        "ok": status.get("ok"),
        "components": status.get("components", []),
        "venues": _venues(),
        "venue_cards": venue_cards(),
        "watchlist": desk_watchlist(),
        "dry_run": os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"},
        "topstep_trading_enabled": os.getenv("TOPSTEP_TRADING_ENABLED", "false"),
        "paper_trades": _paper_trades(20),
        "signals": _signals(20),
        "circuit_breaker": breaker,
        "focus_backtest": backtest,
        "hummingbot_controller_count": hb.get("controller_count", 0),
        "hummingbot_script_count": hb.get("script_count", 0),
        "vibe_skill_count": vibe.get("skill_count", 0),
        "vibe_factor_count": vibe.get("factor_count", 0),
        "hummingbot_controllers": (hb.get("controllers") or [])[:20],
        "vibe_skills": (vibe.get("skills") or [])[:24],
    }
