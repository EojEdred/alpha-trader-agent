"""
Alpha Trader MCP server for personal Fincept Terminal use.

Read-only tools over local Alpha Trader state (paper trades, signals,
circuit breakers, backtest summary). Attach this as an external MCP
server inside Fincept: Settings → MCP Servers.

This process never places live orders.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

mcp = FastMCP(
    "alpha-trader",
    instructions=(
        "Alpha Trader platform sidecar for Fincept Terminal. "
        "Dexter brain plus Hummingbot catalog, Vibe-Trading skills, "
        "and AutoHedge swarm status. Does not place live orders."
    ),
)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str)


@mcp.tool()
def get_paper_trades(limit: int = 25) -> str:
    """Return the latest Alpha Trader paper / dry-run intents."""
    path = DATA / "paper_trades.csv"
    if not path.exists():
        return _dump({"trades": [], "note": "no paper_trades.csv yet"})
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return _dump({"count": len(rows), "trades": rows[-max(1, limit) :]})


@mcp.tool()
def get_signals(limit: int = 25, symbol: Optional[str] = None) -> str:
    """Return recorded Alpha Trader signals, optionally filtered by symbol."""
    rows = _read_json(DATA / "signals" / "signals.json", [])
    if not isinstance(rows, list):
        rows = []
    if symbol:
        needle = symbol.upper()
        rows = [r for r in rows if str(r.get("symbol", "")).upper() == needle]
    return _dump({"count": len(rows), "signals": rows[-max(1, limit) :]})


@mcp.tool()
def get_circuit_breaker() -> str:
    """Return daily PnL halt state used by Alpha Trader risk controls."""
    return _dump(_read_json(DATA / "circuit_breaker_state.json", {}))


@mcp.tool()
def get_focus_backtest() -> str:
    """Return the latest 90-day focus-strategy backtest summary."""
    return _dump(_read_json(DATA / "backtest_focus_result.json", {}))


@mcp.tool()
def get_venue_status() -> str:
    """Return which venue credentials are present without exposing secrets."""

    def present(name: str) -> bool:
        value = os.getenv(name, "").strip()
        return bool(value)

    return _dump(
        {
            "dry_run": os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes"},
            "topstep_trading_enabled": os.getenv("TOPSTEP_TRADING_ENABLED", "false"),
            "venues": {
                "oanda": present("OANDA_API_KEY") and present("OANDA_ACCOUNT_ID"),
                "schwab": present("SCHWAB_APP_KEY") and present("SCHWAB_APP_SECRET"),
                "topstep_projectx": present("PROJECT_X_API_KEY")
                and present("PROJECT_X_USERNAME"),
                "kalshi": present("KALSHI_API_KEY"),
                "polymarket": present("POLYMARKET_API_KEY"),
                "crypto": present("CRYPTO_API_KEY"),
                "massive": present("MASSIVE_API_KEY"),
            },
        }
    )


@mcp.tool()
def get_platform_status() -> str:
    """Health of Dexter, Fincept, Hummingbot, Vibe-Trading, and AutoHedge."""
    from alpha_platform.registry import component_status

    return _dump(component_status())


@mcp.tool()
def list_hummingbot_strategies() -> str:
    """List Hummingbot controllers and scripts from the local fork (no live start)."""
    from alpha_platform.registry import hummingbot_inventory

    inv = hummingbot_inventory()
    return _dump(
        {
            "controllers": inv.get("controllers", []),
            "scripts": inv.get("scripts", []),
            "live_ready": inv.get("live_ready"),
            "note": inv.get("note"),
        }
    )


@mcp.tool()
def list_vibe_skills(limit: int = 40) -> str:
    """List Vibe-Trading research skills from the local fork."""
    from alpha_platform.registry import vibe_inventory

    inv = vibe_inventory()
    skills = inv.get("skills", [])[: max(1, limit)]
    return _dump(
        {
            "skill_count": inv.get("skill_count"),
            "factor_count": inv.get("factor_count"),
            "skills": skills,
            "note": inv.get("note"),
        }
    )


@mcp.tool()
def get_desk() -> str:
    """Full Alpha Trader desk snapshot for the Fincept UI."""
    from alpha_platform.registry import desk_payload

    return _dump(desk_payload())


@mcp.tool()
def get_autohedge_status() -> str:
    """Report whether the local AutoHedge fork is importable."""
    from alpha_platform.registry import autohedge_inventory

    return _dump(autohedge_inventory())


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
