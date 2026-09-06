"""Launch helpers for Fincept and the platform dashboard."""

from __future__ import annotations

import subprocess
from typing import Dict

from alpha_platform.paths import compiled_terminal_app, forks


def launch_fincept() -> Dict[str, str]:
    built = compiled_terminal_app()
    if built.exists():
        subprocess.Popen(["open", str(built)])
        return {"status": "launched", "app": str(built), "kind": "compiled"}
    app = forks().fincept_app
    if not app.exists():
        return {"status": "missing", "detail": "No compiled terminal and stock FinceptTerminal.app is not installed"}
    subprocess.Popen(["open", "-a", "FinceptTerminal"])
    return {"status": "launched", "app": str(app), "kind": "stock"}
