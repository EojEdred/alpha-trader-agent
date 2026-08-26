#!/usr/bin/env bash
# Expose the Alpha Trader API securely over the internet via Cloudflare Tunnel.
# This lets you use the dashboard from anywhere without opening firewall ports.
#
# Prerequisites:
#   - Cloudflare account with the allternit zone
#   - cloudflared installed: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
#   - API running locally on port 8082 (or set ALPHA_TRADER_API_PORT)
#
# Usage:
#   ./scripts/setup-cloudflare-tunnel.sh <subdomain>
# Example:
#   ./scripts/setup-cloudflare-tunnel.sh alphatrader-api

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SUBDOMAIN="${1:-alphatrader-api}"
API_PORT="${ALPHA_TRADER_API_PORT:-8082}"
TUNNEL_DIR="${PROJECT_ROOT}/.cloudflared"
TUNNEL_NAME="alphatrader-api"

if ! command -v cloudflared &> /dev/null; then
  echo "ERROR: cloudflared is not installed."
  echo "Install it from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

mkdir -p "${TUNNEL_DIR}"

# Login if needed
if [ ! -f "${HOME}/.cloudflared/cert.pem" ]; then
  echo "Logging into Cloudflare..."
  cloudflared tunnel login
fi

# Create tunnel if it doesn't exist
if ! cloudflared tunnel list | grep -q "${TUNNEL_NAME}"; then
  echo "Creating tunnel: ${TUNNEL_NAME}"
  cloudflared tunnel create "${TUNNEL_NAME}"
else
  echo "Tunnel ${TUNNEL_NAME} already exists."
fi

TUNNEL_ID=$(cloudflared tunnel list | grep "${TUNNEL_NAME}" | awk '{print $1}')
ACCOUNT_TAG=$(cloudflared tunnel list | grep "${TUNNEL_NAME}" | awk '{print $2}')

echo "Tunnel ID: ${TUNNEL_ID}"
echo "Account Tag: ${ACCOUNT_TAG}"

# Write config
cat > "${TUNNEL_DIR}/config.yml" << EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${HOME}/.cloudflared/${TUNNEL_ID}.json

ingress:
  - hostname: ${SUBDOMAIN}.allternit.com
    service: http://localhost:${API_PORT}
  - service: http_status:404
EOF

echo "Config written to ${TUNNEL_DIR}/config.yml"

# Route DNS
cloudflared tunnel route dns "${TUNNEL_NAME}" "${SUBDOMAIN}.allternit.com" || true

echo ""
echo "To start the tunnel, run one of:"
echo "  cloudflared tunnel --config ${TUNNEL_DIR}/config.yml run"
echo "  cloudflared tunnel run ${TUNNEL_NAME}"
echo ""
echo "Your API will be available at: https://${SUBDOMAIN}.allternit.com"
echo "Set VITE_API_BASE_URL=https://${SUBDOMAIN}.allternit.com when building the dashboard."
