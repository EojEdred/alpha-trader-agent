#!/bin/bash
set -e

# Alpha Trader One-Command Installer
# Supports macOS (launchd) and Linux (systemd)

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"
SERVICE_NAME="alpha-trader"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[Alpha Trader]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[Warning]${NC} $1"
}

error() {
    echo -e "${RED}[Error]${NC} $1"
    exit 1
}

# Detect OS
OS="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
else
    error "Unsupported OS: $OSTYPE. This installer supports macOS and Linux only."
fi

log "Detected OS: $OS"

# Check Python
PYTHON_CMD=""
if command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3.13 &> /dev/null; then
    PYTHON_CMD="python3.13"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    error "Python 3 is required but not installed."
fi

PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | awk '{print $2}')
log "Using Python: $PYTHON_VERSION"

# Verify Python >= 3.10
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    error "Python 3.10 or higher is required. Found ${PYTHON_VERSION}."
fi

# Install system dependencies on Linux
if [ "$OS" == "linux" ]; then
    log "Installing system dependencies (requires sudo)..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y build-essential curl git libffi-dev libssl-dev \
            libxml2-dev libxslt1-dev libjpeg-dev libpng-dev libtiff-dev \
            libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
            python3-venv python3-pip
    elif command -v yum &> /dev/null; then
        sudo yum groupinstall -y "Development Tools"
        sudo yum install -y curl git libffi-devel openssl-devel libxml2-devel \
            libxslt-devel libjpeg-devel libpng-devel libtiff-devel mesa-libGL
    else
        warn "Could not detect package manager. You may need to install build tools manually."
    fi
fi

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtual environment..."
    $PYTHON_CMD -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Upgrade pip
log "Upgrading pip..."
pip install --upgrade pip setuptools wheel -q

# Install project
log "Installing Alpha Trader package..."
pip install -e . -q

# Install additional runtime dependencies
log "Installing broker/API dependencies..."
pip install -q \
    schwab-py \
    yfinance \
    polygon-api-client \
    numpy \
    pandas \
    requests \
    Authlib \
    python-jose \
    ccxt \
    pyyaml \
    oandapyV20

# Install Kimi Code CLI (TypeScript binary) for chat/brain inference
if ! command -v kimi &> /dev/null; then
    log "Installing Kimi Code CLI..."
    curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
    mkdir -p "$HOME/.local/bin"
    ln -sf "$HOME/.kimi-code/bin/kimi" "$HOME/.local/bin/kimi"
fi

# Install Playwright browsers and system deps
log "Installing Playwright browsers..."
if [ "$OS" == "linux" ]; then
    playwright install-deps chromium
fi
playwright install chromium

# Create .env template if missing
if [ ! -f "$PROJECT_DIR/.env" ]; then
    log "Creating .env template..."
    cat > "$PROJECT_DIR/.env" <<'ENV'
# Charles Schwab API Credentials
SCHWAB_APP_KEY=
SCHWAB_APP_SECRET=
SCHWAB_REDIRECT_URI=https://your-domain-or-tunnel/callback
SCHWAB_TOKEN_PATH=schwab_token.json

# Web dashboard password
DEXTER_WEB_PASSWORD=alpha2026

# Trading mode
ALPHA_TRADER_AUTO_START=true
ALPHA_TRADER_DRY_RUN=false

# AI provider for chat/brain (kimi, kimi-api, codex-cli, gemini-cli)
# For VPS/cloud installs, set KIMI_API_KEY so the device-bound OAuth token is not required.
LLM_PROVIDER=kimi
KIMI_CLI_PATH=/root/.kimi-code/bin/kimi
# KIMI_API_KEY=your_moonshot_key
# KIMI_API_BASE=https://api.moonshot.ai/v1
# KIMI_API_MODEL=kimi-k2

# Optional venue credentials (add as needed)
# OANDA_API_KEY=
# TOPSTEP_USERNAME=
# TOPSTEP_PASSWORD=
# KALSHI_API_KEY=
# KALSHI_API_SECRET=
# POLYGON_API_KEY=
ENV
    warn "Created .env template. Please edit it and add your API credentials."
else
    log ".env already exists. Skipping template creation."
fi

# Create logs directory
mkdir -p "$PROJECT_DIR/logs" "$PROJECT_DIR/data"

# Install service (can be skipped with SKIP_SERVICE_START=1 for testing)
if [ "${SKIP_SERVICE_START:-0}" == "1" ]; then
    warn "SKIP_SERVICE_START=1 — service files created but not loaded."
fi

if [ "$OS" == "macos" ]; then
    log "Installing launchd service..."
    PLIST_PATH="$HOME/Library/LaunchAgents/com.allternit.alpha-trader.plist"
    cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.allternit.alpha-trader</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/python</string>
        <string>${PROJECT_DIR}/cli.py</string>
        <string>serve</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>8080</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/logs/launchd_serve_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/logs/launchd_serve_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${VENV_DIR}/bin:$HOME/.kimi-code/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>ALPHA_TRADER_AUTO_START</key>
        <string>true</string>
        <key>ALPHA_TRADER_DRY_RUN</key>
        <string>false</string>
        <key>LLM_PROVIDER</key>
        <string>kimi</string>
        <key>KIMI_CLI_PATH</key>
        <string>$HOME/.kimi-code/bin/kimi</string>
    </dict>
</dict>
</plist>
PLIST
    if [ "${SKIP_SERVICE_START:-0}" != "1" ]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        launchctl load "$PLIST_PATH" || warn "Failed to load launchd service."
    fi
    log "Service installed. Start with: launchctl load $PLIST_PATH"

elif [ "$OS" == "linux" ]; then
    log "Installing systemd service..."
    SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
    if [ "$EUID" -ne 0 ]; then
        warn "Need sudo to install systemd service. Re-run with sudo, or install manually."
    else
        SERVICE_USER="${SUDO_USER:-$USER}"
        if [ -z "$SERVICE_USER" ]; then
            SERVICE_USER="root"
        fi
        cat > "$SERVICE_PATH" <<SERVICE
[Unit]
Description=Alpha Trader Daemon
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${PROJECT_DIR}
Environment="PATH=${VENV_DIR}/bin:/root/.kimi-code/bin:/root/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
Environment="ALPHA_TRADER_AUTO_START=true"
Environment="ALPHA_TRADER_DRY_RUN=false"
Environment="LLM_PROVIDER=kimi"
Environment="KIMI_CLI_PATH=/root/.kimi-code/bin/kimi"
ExecStart=${VENV_DIR}/bin/python ${PROJECT_DIR}/cli.py serve --host 0.0.0.0 --port 8080
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE
        systemctl daemon-reload
        systemctl enable "$SERVICE_NAME"
        if [ "${SKIP_SERVICE_START:-0}" != "1" ]; then
            systemctl start "$SERVICE_NAME" || warn "Failed to start systemd service."
        fi
        log "Service installed. Start with: sudo systemctl start $SERVICE_NAME"
    fi
fi

log "Installation complete."
log ""
log "Next steps:"
log "  1. Edit ${PROJECT_DIR}/.env with your credentials"
log "  2. Authenticate Schwab and place schwab_token.json in ${PROJECT_DIR}/"
log "  3. Start the service (or it may already be running on macOS)"
log "  4. Open dashboard: http://localhost:8080/"
log ""
log "Commands:"
log "  ${VENV_DIR}/bin/alphatrader serve       # Run dashboard manually"
log "  ${VENV_DIR}/bin/alphatrader dashboard   # Run TUI dashboard"
