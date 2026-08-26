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

---

# Hosting Alpha Trader on Cloudflare (Private, Persistent)

This setup puts the dashboard on a real domain under your existing allternit Cloudflare account, keeps the API private, and lets you log in from anywhere.

## Architecture

- **Frontend**: Cloudflare Pages (`alphatrader.allternit.com`)
- **Backend API**: Runs on your Mac/VPS, exposed via Cloudflare Tunnel (`alphatrader-api.allternit.com`)
- **Access control**: Dashboard password + optional Cloudflare Access policy so only you can open it

## 1. Install and run the API at home or on a VPS

```bash
git clone <repo> alpha-trader
cd alpha-trader
scripts/install.sh
```

Edit `.env` and set at least:

```env
DEXTER_WEB_PASSWORD=your-strong-password
TRADOVATE_USERNAME=
TRADOVATE_PASSWORD=
TRADOVATE_ACCOUNT_ID=
TRADOVATE_DEMO=true
```

Start the API:

```bash
./venv/bin/alphatrader dashboard --host 127.0.0.1 --port 8082
```

Or let the system service run it on boot.

## 2. Expose the API with Cloudflare Tunnel

Install `cloudflared`: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

Run the setup helper:

```bash
./scripts/setup-cloudflare-tunnel.sh alphatrader-api
```

This will:
- Log you into Cloudflare
- Create a tunnel named `alphatrader-api`
- Point `alphatrader-api.allternit.com` to `http://localhost:8082`
- Write a config file to `.cloudflared/config.yml`

Start the tunnel:

```bash
cloudflared tunnel --config .cloudflared/config.yml run
```

For persistence, run the tunnel as a service:

```bash
cloudflared service install
```

## 3. Deploy the frontend to Cloudflare Pages

Install Node.js dependencies:

```bash
cd web
npm ci
```

Set the API origin:

```bash
export VITE_API_BASE_URL=https://alphatrader-api.allternit.com
```

Build and deploy:

```bash
npm run build
npx wrangler pages deploy dist --project-name alphatrader
```

Or use the helper script:

```bash
export CLOUDFLARE_API_TOKEN=...
export VITE_API_BASE_URL=https://alphatrader-api.allternit.com
./scripts/deploy-cloudflare-pages.sh
```

## 4. Add a custom domain

In the Cloudflare dashboard:
1. Go to **Pages** → `alphatrader` → **Custom domains**
2. Add `alphatrader.allternit.com`
3. Cloudflare will add the DNS record automatically

## 5. Lock it down (optional but recommended)

### Option A: Cloudflare Access (zero-trust login)
In the Cloudflare dashboard:
1. Go to **Zero Trust** → **Access** → **Applications**
2. Add a self-hosted app for `alphatrader.allternit.com`
3. Create a policy allowing only your email address

### Option B: Dashboard password only
The built-in password (`DEXTER_WEB_PASSWORD`) is required for all API calls. Keep it strong and unique.

## Updating on the road

When you buy a new account (e.g., Apex/Tradovate):

1. Open `https://alphatrader.allternit.com`
2. Log in with your dashboard password
3. Go to **Settings → Apex / Tradovate**
4. Fill in the credentials and save
5. The API reloads them automatically — no restart needed

## Important notes

- The API backend must stay running wherever you host it. The Cloudflare Tunnel keeps it reachable without opening firewall ports.
- If your home IP changes, Cloudflare Tunnel handles it automatically.
- Cloudflare Pages serves only the frontend; all secrets stay on the API backend.
- Do not commit `.env` or Cloudflare tunnel credentials to git.
