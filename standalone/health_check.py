"""
Health Check HTTP Server for Alpha Trader

Provides a lightweight endpoint for monitoring the daemon status.
Used by systemd/LaunchAgent for restart decisions and external monitoring.
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from loguru import logger

HEALTH_PORT = 8765

# Shared state (updated by the main app)
_health_server = None

# Shared state (updated by the main app)
_health_state = {
    "status": "starting",
    "scheduler_running": False,
    "last_trade_time": None,
    "last_heartbeat": None,
    "schwab_connected": False,
    "open_positions_count": 0,
    "errors_last_hour": 0,
}


def update_health(**kwargs):
    """Update health state from the main application."""
    _health_state.update(kwargs)
    _health_state["last_heartbeat"] = datetime.now(timezone.utc).isoformat()


def get_health() -> dict:
    """Compute current health status."""
    state = _health_state.copy()
    
    # Check heartbeat freshness
    heartbeat = state.get("last_heartbeat")
    if heartbeat:
        try:
            hb_dt = datetime.fromisoformat(heartbeat)
            elapsed = (datetime.now(timezone.utc) - hb_dt).total_seconds()
            if elapsed > 600:  # 10 minutes
                state["status"] = "stale"
            else:
                state["status"] = "ok"
        except Exception:
            state["status"] = "unknown"
    
    return state


class HealthHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health endpoint."""
    
    def log_message(self, format, *args):
        # Suppress default logging to avoid spam
        pass
    
    def do_GET(self):
        if self.path == "/health":
            health = get_health()
            body = json.dumps(health, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Alpha Trader Health Check\nUse /health for JSON status\n")
        else:
            self.send_response(404)
            self.end_headers()


def start_health_server(port: int = HEALTH_PORT):
    """Start the health check HTTP server in a background thread."""
    global _health_server
    if _health_server is not None:
        return _health_server

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _health_server = server
    logger.info(f"Health check server running on http://0.0.0.0:{port}/health")
    return server


# Standalone test
if __name__ == "__main__":
    update_health(scheduler_running=True, schwab_connected=True)
    server = start_health_server()
    print(f"Health server running on port {HEALTH_PORT}")
    print("Press Ctrl+C to stop")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        server.shutdown()
