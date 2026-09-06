# Personal Fincept Terminal + Alpha Trader

Local, personal-use only. Fincept Terminal stays a separate AGPL app.
Alpha Trader stays the brain. They talk over MCP. Nothing here is for
production or a public rebrand.

## Layout

| Piece | Path |
|---|---|
| Fincept app | `/Applications/FinceptTerminal.app` (v4.5.0) |
| Fincept source (AGPL) | `../alpha-trader-terminal` |
| Fincept fork | https://github.com/Gizziio/alpha-trader-terminal |
| Hummingbot fork | https://github.com/Gizziio/alpha-trader-hummingbot |
| Vibe-Trading fork | https://github.com/Gizziio/alpha-trader-vibe-trading |
| AutoHedge fork | https://github.com/Gizziio/alpha-trader-autohedge |
| Alpha Trader | this repo |
| MCP sidecar | `tools/alpha_trader_mcp_server.py` |

Do not copy Fincept source into this git repo or push it to GitHub.

## Desktop UI

Fincept Terminal **is** the UI. The source is copied into `terminal/`
(AGPL-3.0). The Alpha Trader desk (`src/screens/alpha_trader/`) is the
home screen of a build from that tree. The installed 4.5.0 app is the
stock binary until Qt 6.8.3 is used to compile `terminal/fincept-qt`.

## Start the platform

```bash
cd /Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent
source venv/bin/activate
python cli.py platform start
```

This boots Dexter on `:8080`, opens Fincept, and prints the MCP attach block.
Web terminal: `http://127.0.0.1:8080/platform`

Hummingbot live bots stay **off** until the conda/Cython env is built.
Vibe-Trading is catalogued from the fork (skills + factors).
AutoHedge runs through Dexter's existing director, with the local fork on `sys.path`.

## Attach Alpha Trader inside Fincept

1. Open **Fincept Terminal**.
2. Continue as Guest.
3. Settings → MCP Servers → add:

```
Name:        Alpha Trader
Command:     /Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent/venv/bin/python
Args:        /Users/joe/Desktop/allternit-workspace/allternit-alpha-trader-agent/tools/alpha_trader_mcp_server.py
Auto-start:  on
```

Or from this repo:

```bash
source venv/bin/activate
python cli.py mcp serve
```

## Tools the sidecar exposes (read-only)

- `get_paper_trades`
- `get_signals`
- `get_circuit_breaker`
- `get_focus_backtest`
- `get_venue_status`

No live orders go through this server.

## License boundary

Fincept Terminal is AGPL-3.0 + Fincept trademarks. Personal use of their
app and source on this machine is allowed. Rebranding it as Alpha Trader
and distributing it is not.
