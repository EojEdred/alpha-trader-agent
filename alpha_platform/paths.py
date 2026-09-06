"""Locate sibling forks, the Fincept app, and this repo."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = AGENT_ROOT.parent


@dataclass(frozen=True)
class Forks:
    agent: Path
    fincept_src: Path
    hummingbot: Path
    vibe: Path
    autohedge: Path
    fincept_app: Path

    def as_dict(self) -> dict:
        return {
            "agent": str(self.agent),
            "fincept_src": str(self.fincept_src),
            "hummingbot": str(self.hummingbot),
            "vibe": str(self.vibe),
            "autohedge": str(self.autohedge),
            "fincept_app": str(self.fincept_app),
        }


def forks() -> Forks:
    return Forks(
        agent=AGENT_ROOT,
        fincept_src=(AGENT_ROOT / "terminal")
        if (AGENT_ROOT / "terminal" / "fincept-qt").exists()
        else WORKSPACE / "alpha-trader-terminal",
        hummingbot=WORKSPACE / "alpha-trader-hummingbot",
        vibe=WORKSPACE / "alpha-trader-vibe-trading",
        autohedge=WORKSPACE / "alpha-trader-autohedge",
        fincept_app=Path("/Applications/FinceptTerminal.app"),
    )


def compiled_terminal_app() -> Path:
    """In-tree Qt build of the Alpha Trader desk, if it exists."""
    return (
        AGENT_ROOT
        / "terminal"
        / "fincept-qt"
        / "build"
        / "macos-release"
        / "FinceptTerminal.app"
    )


def ensure_autohedge_on_path() -> bool:
    """Put the local AutoHedge fork on sys.path so `import autohedge` works."""
    import sys

    root = forks().autohedge
    if not root.exists():
        return False
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    return True
