# 🚀 Alpha Trader (Dexter)

Alpha Trader (Dexter) is a fully autonomous, multi-modal trading research and execution system. It is designed to run 24/7 on a local machine or VPS, scanning markets, analyzing setups with an AI brain, and executing options/futures trades based on defined rules.

**The desktop UI is Fincept Terminal**, vendored under `terminal/` (AGPL-3.0). Dexter is the brain on `:8080`. The Alpha Trader desk is the home screen of that Qt terminal. A React dashboard remains as a fallback web view.

### 📥 Packaged Download
You can download the latest pre-packaged, zero-configuration version of the app directly from GitHub:
👉 **[Download Alpha Trader (alpha-trader-package.zip)](https://github.com/EojEdred/alpha-trader-agent/releases/download/v1.0.0/alpha-trader-package.zip)**

*(Contains pre-compiled frontend assets. Excludes all private `.env` keys and credentials for security)*

---

## ✨ Features

- **Built-in Web Command Center**: A sleek, dark-themed, glassmorphic React dashboard for real-time monitoring and control.
- **Interactive Configuration Panel**: Add your API credentials, configure Telegram alerts, set up the AI Brain, and manage Schwab integration right in the web UI.
- **Schwab Options Trading**: Fully automated options routing with automatic token health checking and refresh alerts.
- **AI Brain Confluence**: Leverage LLMs (OpenAI, Gemini, Anthropic, or Kimi) to score trade setups, verify charts, and analyze morning reports.
- **FMZ Quant Strategy Library**: Imports the full [fmzquant/strategies](https://github.com/fmzquant/strategies) catalog (~5,800 strategies) and wraps runnable JavaScript/Python strategies as Alpha Trader signals.
- **Multi-Modal Execution**: Seamlessly falls back from direct API execution to browser-based Playwright automation, and desktop GUI click actions if API endpoints fail.
- **Real-Time Log Stream**: Stream system logs and diagnostic terminals directly to your web browser.

---

## 🛠️ Onboarding & Installation

Onboarding a new instance of Alpha Trader takes just a few steps:

### 1. Clone the Repository
```bash
git clone <your-repository-url> alpha-trader
cd alpha-trader
```

### 2. Run the Installer
Run the one-command installer script. This will set up the Python virtual environment (`venv`), install all required dependencies (including Playwright browser binaries), and register the system service (macOS launchd or Linux systemd) so it runs automatically in the background.
```bash
chmod +x scripts/install.sh
./scripts/install.sh
```

### 3. Start the terminal
```bash
source venv/bin/activate
python cli.py platform start
```
This starts Dexter and opens **Fincept Terminal** (the desktop UI). Source for that UI is in `terminal/` (AGPL-3.0). After a Qt 6.8.3 build of `terminal/fincept-qt`, the home desk is **Alpha Trader**.

Web fallback (optional): `python cli.py dashboard` then `http://localhost:8080/`.

### 4. Configure via Web Settings
Once logged in:
1. Head over to the **Settings** page in the sidebar.
2. Update the **Dashboard Password** to secure your command center.
3. Configure your **Telegram Bot Token** and **Chat ID** to receive live execution logs.
4. Set up your **AI Brain** (select your LLM Provider and input your API keys).
5. Input your broker credentials:
   - **Schwab Developer Portal** keys for Schwab options.
   - **OANDA** API credentials for FX.
   - **Kalshi** or **Topstep** details for events and futures.
6. Click **Save Configuration** and then **Restart Service Daemon** to apply all updates.

### 5. Charles Schwab OAuth Verification
To complete your Schwab options authorization:
1. Open your terminal in the project directory.
2. Run the Schwab OAuth helper:
   ```bash
   python reauth_schwab.py
   ```
3. A browser window will open requesting you to log into your Schwab account and authorize the app. Click **Allow**, and the local callback server will automatically save the token securely as `schwab_token.json`.

---

## ⚙️ Usage Commands

Alpha Trader includes a powerful CLI utility (`cli.py`) to run and test workflows:

```bash
# Start the scheduler (runs jobs continuously in live or dry-run mode)
python cli.py run --dry-run
python cli.py run --venue schwab

# Trigger a manual single scan & execution cycle
python cli.py agent-cycle --dry-run

# Generate a morning market briefing
python cli.py brief

# Run prediction market arbitrage scanner
python cli.py arb

# Desktop UI (Fincept) + Dexter
python cli.py platform start

# React fallback web dashboard
python cli.py dashboard

# Run research / analyst / audit commands
python cli.py research run --symbols SPY,QQQ,AAPL
python cli.py research agendas
python cli.py analyst list
python cli.py analyst run technical_analyst SPY
python cli.py autohedge run "hedge AAPL vs QQQ"
python cli.py valuecell analyze AAPL
python cli.py audit list
python cli.py audit verify
```

---

## 📁 Repository Structure

```
├── cli.py                  # CLI command center entry point
├── terminal/               # Desktop UI (Fincept Qt, AGPL-3.0)
│   └── fincept-qt/         # C++20/Qt6 workstation; Alpha Trader is the home desk
├── dexter/                 # FastAPI brain
├── config/                 # YAML configuration templates
├── python-gateway/         # FastAPI microservice for local tool executions
├── scripts/                # Installation and authentication scripts
├── standalone/             # Scheduler daemon and workflow engines
├── tools/                  # Market feeds, broker connectors, and strategy brains
├── web/                    # React fallback dashboard
└── workflows/              # Structured trading schemas (YAML files)
```

---

## 🔒 Security Notes
- **Never commit `.env` or `schwab_token.json`** to public source control. They are pre-configured in `.gitignore` to prevent leaks.
- All secrets entered via the Web Dashboard are written directly to your local `.env` file on disk. No data leaves your machine/VPS unless it is communicated directly to your chosen broker APIs, LLMs, or Telegram.
- For secure deployment on a public VPS, we recommend setting up a basic reverse proxy (like Caddy or Nginx) with HTTPS, or running a Cloudflare Tunnel.
