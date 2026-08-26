"""
Alpha Trader — Polished Textual TUI Dashboard

A Bloomberg-terminal-inspired live dashboard showing:
- Agent health & status
- Recent trade feed with P&L
- Risk metrics (circuit breaker, daily limits)
- Live log stream
- System uptime & mode

Usage:
    dexter dashboard
    python -m dexter.tui
"""

import asyncio
from datetime import datetime
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Header,
    Footer,
    Static,
    DataTable,
    Log,
    Label,
    Rule,
)
from textual.widget import Widget
from textual.color import Color

from dexter.state import SystemState, get_state, AgentStatus, SystemMode


# ─── APPLE-INSPIRED LIGHT THEME ───
COLOR_BG = "#F5F5F0"        # eggshell white
COLOR_PANEL = "#FAFAF8"     # warm white panels
COLOR_SURFACE = "#FFFFFF"   # pure white surfaces
COLOR_BORDER = "#D1D1D6"    # light Apple gray
COLOR_TEXT = "#1C1C1E"      # near black
COLOR_DIM = "#8E8E93"       # secondary gray
COLOR_GREEN = "#34C759"     # Apple green
COLOR_RED = "#FF3B30"       # Apple red
COLOR_YELLOW = "#FFCC00"    # Apple yellow
COLOR_BLUE = "#007AFF"      # Apple blue
COLOR_ORANGE = "#FF9500"


class StatusBadge(Widget):
    """A small colored status badge."""

    def __init__(self, label: str, color: str, **kwargs):
        super().__init__(**kwargs)
        self._label = label
        self._color = color

    def compose(self) -> ComposeResult:
        yield Static(f"[b {self._color}]{self._label}[/]", classes="badge")


class AgentPanel(Widget):
    """Panel showing agent health status."""

    DEFAULT_CSS = """
    AgentPanel {
        border: round $border;
        background: $panel;
        color: $text;
        padding: 1;
        height: 100%;
    }
    AgentPanel .panel-title {
        color: $text;
        text-style: bold;
    }
    AgentPanel .agent-row {
        height: auto;
        margin: 0 0 1 0;
    }
    AgentPanel .agent-name {
        width: 20;
        color: $text;
    }
    AgentPanel .agent-status {
        width: 10;
    }
    AgentPanel .agent-action {
        color: $dim;
    }
    AgentPanel Rule {
        color: $border;
    }
    """
    def compose(self) -> ComposeResult:
        yield Label("[b]AGENTS[/b]", classes="panel-title")
        yield Rule()
        self._rows = Container(classes="agent-rows")
        yield self._rows

    def on_mount(self):
        self.update()
        self.set_interval(1.0, self.update)

    def update(self):
        state = get_state()
        self._rows.remove_children()
        for name, agent in state.agents.items():
            color = {
                AgentStatus.IDLE: COLOR_GREEN,
                AgentStatus.BUSY: COLOR_BLUE,
                AgentStatus.ERROR: COLOR_RED,
                AgentStatus.OFFLINE: COLOR_DIM,
            }.get(agent.status, COLOR_DIM)

            icon = {
                AgentStatus.IDLE: "●",
                AgentStatus.BUSY: "◐",
                AgentStatus.ERROR: "✕",
                AgentStatus.OFFLINE: "◦",
            }.get(agent.status, "?")

            action = agent.last_action or "—"
            if agent.error:
                action = f"[red]Error: {agent.error}[/red]"

            row = Static(
                f"[{color}]{icon}[/] [b]{name:18}[/] "
                f"[{color}]{agent.status.value.upper():8}[/]  {action}",
                classes="agent-row",
            )
            self._rows.mount(row)


class TradePanel(Widget):
    """Panel showing recent trade feed."""

    DEFAULT_CSS = """
    TradePanel {
        border: round $border;
        background: $panel;
        color: $text;
        padding: 1;
        height: 100%;
    }
    TradePanel .panel-title {
        color: $text;
        text-style: bold;
    }
    TradePanel DataTable {
        background: $panel;
        color: $text;
    }
    TradePanel DataTable > .datatable--header {
        background: $surface;
        color: $text;
        text-style: bold;
    }
    TradePanel Rule {
        color: $border;
    }
    """
    def compose(self) -> ComposeResult:
        yield Label("[b]TRADES[/b]", classes="panel-title")
        yield Rule()
        self._table = DataTable(cursor_type="row", show_header=True, show_cursor=False)
        self._table.add_columns("Time", "Symbol", "Dir", "Size", "Venue", "Method", "Status", "P&L")
        yield self._table

    def on_mount(self):
        self.update()
        self.set_interval(1.0, self.update)

    def update(self):
        state = get_state()
        self._table.clear()
        for trade in state.trades[:20]:
            ts = trade.timestamp.strftime("%H:%M:%S")
            dir_color = COLOR_GREEN if trade.direction == "long" else COLOR_RED
            pnl_str = ""
            if trade.pnl is not None:
                pnl_color = COLOR_GREEN if trade.pnl >= 0 else COLOR_RED
                pnl_str = f"[{pnl_color}]{trade.pnl:+.2f}[/{pnl_color}]"
            status_color = COLOR_GREEN if trade.status in ("filled", "success") else COLOR_RED
            self._table.add_row(
                ts,
                f"[b]{trade.symbol}[/b]",
                f"[{dir_color}]{trade.direction[:3].upper()}[/{dir_color}]",
                str(trade.size or "—"),
                trade.venue,
                trade.method,
                f"[{status_color}]{trade.status}[/{status_color}]",
                pnl_str,
            )


class RiskPanel(Widget):
    """Panel showing risk metrics."""

    DEFAULT_CSS = """
    RiskPanel {
        border: round $border;
        background: $panel;
        color: $text;
        padding: 1;
        height: 100%;
    }
    RiskPanel .panel-title {
        color: $text;
        text-style: bold;
    }
    RiskPanel .risk-content {
        color: $text;
    }
    RiskPanel Rule {
        color: $border;
    }
    """
    def compose(self) -> ComposeResult:
        yield Label("[b]RISK & LIMITS[/b]", classes="panel-title")
        yield Rule()
        self._content = Static("", classes="risk-content")
        yield self._content

    def on_mount(self):
        self.update()
        self.set_interval(1.0, self.update)

    def update(self):
        state = get_state()
        risk = state.risk

        lines = []
        cb_color = COLOR_RED if risk.circuit_breaker_active else COLOR_GREEN
        cb_text = "TRIPPED" if risk.circuit_breaker_active else "OK"
        lines.append(f"Circuit Breaker: [{cb_color}]{cb_text}[/{cb_color}]")
        lines.append("")

        lines.append("[b]Daily Trade Counts:[/b]")
        for venue, count in risk.daily_trades.items():
            limit = risk.daily_limits.get(venue, "∞")
            pct = count / limit * 100 if isinstance(limit, int) and limit > 0 else 0
            color = COLOR_RED if pct >= 80 else COLOR_GREEN
            lines.append(f"  {venue:12} [{color}]{count}/{limit}[/{color}]")

        lines.append("")
        lines.append("[b]Rate Limit Status:[/b]")
        for venue, limited in risk.rate_limited.items():
            color = COLOR_RED if limited else COLOR_GREEN
            text = "BLOCKED" if limited else "OK"
            lines.append(f"  {venue:12} [{color}]{text}[/{color}]")

        lines.append("")
        lines.append(f"Consecutive Losses: {risk.consecutive_losses}")

        self._content.update("\n".join(lines))


class LogPanel(Widget):
    """Panel showing live log stream."""

    DEFAULT_CSS = """
    LogPanel {
        border: round $border;
        background: $panel;
        color: $text;
        padding: 1;
        height: 100%;
    }
    LogPanel .panel-title {
        color: $text;
        text-style: bold;
    }
    LogPanel .log-view {
        background: $panel;
        color: $text;
    }
    LogPanel Rule {
        color: $border;
    }
    """
    def compose(self) -> ComposeResult:
        yield Label("[b]LOGS[/b]", classes="panel-title")
        yield Rule()
        self._log = Log(classes="log-view")
        yield self._log

    def on_mount(self):
        self._queue = get_state().subscribe()
        self._task = asyncio.create_task(self._poll())
        # Seed with existing logs
        for line in get_state().logs[-50:]:
            self._log.write_line(line)

    async def _poll(self):
        while True:
            try:
                line = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                self._log.write_line(line)
            except asyncio.TimeoutError:
                pass

    def on_unmount(self):
        get_state().unsubscribe(self._queue)
        if self._task:
            self._task.cancel()


class InfoBar(Widget):
    """Top info bar showing system status."""

    DEFAULT_CSS = """
    InfoBar {
        height: 3;
        background: $surface;
        color: $text;
        border-bottom: solid $border;
        padding: 0 2;
    }
    InfoBar .brand {
        color: $primary;
        text-style: bold;
    }
    InfoBar .spacer {
        width: 1fr;
    }
    InfoBar .mode {
        width: auto;
        margin: 0 2;
        color: $text;
    }
    InfoBar .uptime {
        width: auto;
        color: $dim;
    }
    """
    mode_color = reactive(COLOR_DIM)
    uptime = reactive("00:00:00")
    dry_run = reactive(True)

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Static("[b]α Alpha Trader[/b]", classes="brand")
            yield Static("", classes="spacer")
            self._mode = Static("", classes="mode")
            self._uptime = Static("", classes="uptime")
            yield self._mode
            yield self._uptime

    def on_mount(self):
        self.set_interval(1.0, self.update)

    def update(self):
        state = get_state()
        state.tick_uptime()

        mode_colors = {
            SystemMode.STOPPED: COLOR_DIM,
            SystemMode.STARTING: COLOR_YELLOW,
            SystemMode.RUNNING: COLOR_GREEN,
            SystemMode.PAUSED: COLOR_YELLOW,
            SystemMode.ERROR: COLOR_RED,
        }
        self.mode_color = mode_colors.get(state.mode, COLOR_DIM)

        mode_label = state.mode.value.upper()
        if state.dry_run:
            mode_label += " (DRY-RUN)"

        self._mode.update(f"[{self.mode_color}]● {mode_label}[/{self.mode_color}]")

        uptime = state.uptime_seconds
        hours, rem = divmod(int(uptime), 3600)
        minutes, seconds = divmod(rem, 60)
        self._uptime.update(f"◷ {hours:02d}:{minutes:02d}:{seconds:02d}")


class CommandBar(Widget):
    """Bottom command bar."""

    DEFAULT_CSS = """
    CommandBar {
        height: 3;
        background: $surface;
        color: $text;
        border-top: solid $border;
        padding: 0 2;
    }
    CommandBar .commands {
        color: $dim;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[dim]Keys:[/dim] [b]r[/b]un  [b]p[/b]ause  [b]t[/b]rade  [b]c[/b]onfig  [b]q[/b]uit",
            classes="commands",
        )


class AlphaTraderDashboard(App):
    """Main Alpha Trader TUI Dashboard."""

    CSS = f"""
    Screen {{
        background: {COLOR_BG};
        color: {COLOR_TEXT};
    }}
    .panel-title {{
        text-style: bold;
        color: {COLOR_TEXT};
        height: 1;
    }}
    .spacer {{
        width: 1fr;
    }}
    .brand {{
        color: {COLOR_BLUE};
    }}
    .mode {{
        width: auto;
        margin: 0 2;
    }}
    .uptime {{
        width: auto;
        color: {COLOR_DIM};
    }}
    Footer {{
        background: {COLOR_SURFACE};
        color: {COLOR_TEXT};
        border-top: solid {COLOR_BORDER};
    }}
    Footer > .footer--key {{
        color: {COLOR_TEXT};
        background: {COLOR_PANEL};
    }}
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "run", "Run"),
        ("p", "pause", "Pause"),
        ("t", "trade", "Trade"),
        ("c", "config", "Config"),
    ]

    def compose(self) -> ComposeResult:
        yield InfoBar()
        with Horizontal():
            with Vertical(classes="left-col"):
                yield AgentPanel()
                yield RiskPanel()
            with Vertical(classes="right-col"):
                yield TradePanel()
                yield LogPanel()
        yield CommandBar()
        yield Footer()

    def action_run(self):
        state = get_state()
        if state.mode in (SystemMode.STOPPED, SystemMode.PAUSED):
            state.set_mode(SystemMode.RUNNING)
            state.add_log("System resumed by user")
        else:
            state.add_log("System is already running")

    def action_pause(self):
        state = get_state()
        if state.mode == SystemMode.RUNNING:
            state.set_mode(SystemMode.PAUSED)
            state.add_log("System paused by user")
        else:
            state.add_log("System is not running")

    def action_trade(self):
        state = get_state()
        state.add_log("Manual trade dialog not yet implemented — use CLI: dexter trade SYMBOL long")

    def action_config(self):
        state = get_state()
        state.add_log("Config editor not yet implemented — edit ~/.alphatrader/config.yaml")


def main():
    app = AlphaTraderDashboard()
    app.run()


if __name__ == "__main__":
    main()
