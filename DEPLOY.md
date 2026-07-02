# Alpha Trader — Deploy Anywhere

One-command installer for macOS and Linux (including VPS).

## Quick Install

```bash
git clone <your-repo-url> alpha-trader
cd alpha-trader
scripts/install.sh
```

The installer will:
- Create a Python virtual environment (`venv/`)
- Install Alpha Trader and all dependencies
- Install Playwright browsers
- Create a `.env` template if one doesn't exist
- Install and start a system service (`launchd` on macOS, `systemd` on Linux)

## After Install

1. **Edit `.env`** and add your API keys:
   ```bash
   nano .env
   ```

2. **Authenticate Schwab** and place the generated `schwab_token.json` in the project root.

3. **Open the dashboard:**
   ```
   http://your-server-ip:8080/ (or http://localhost:8080/ on the same machine)
   ```
   Default password: `alpha2026` (change in `.env`)

## Service Management

### macOS
```bash
launchctl unload ~/Library/LaunchAgents/com.allternit.alpha-trader.plist
launchctl load ~/Library/LaunchAgents/com.allternit.alpha-trader.plist
```

### Linux
```bash
sudo systemctl start alpha-trader
sudo systemctl stop alpha-trader
sudo systemctl restart alpha-trader
sudo systemctl status alpha-trader
```

## HTTPS Callback for Schwab OAuth

On a VPS, you need a real HTTPS callback URL. Options:

1. **Cloudflare Tunnel** — point tunnel to `http://localhost:8080`
2. **Reverse proxy** — Caddy/nginx with a domain + HTTPS
3. **Temporary tunnel** — serveo.net or ngrok for testing

Update `SCHWAB_REDIRECT_URI` in `.env` and in the Schwab Developer Portal.

## Manual Run

If you don't want the service:
```bash
source venv/bin/activate
alphatrader serve --host 0.0.0.0 --port 8080
```

## Run Without Service

```bash
scripts/run.sh
```
