#!/usr/bin/env bash
# Deploy Alpha Trader frontend to Cloudflare Pages.
# Usage:
#   export CLOUDFLARE_API_TOKEN=...
#   export VITE_API_BASE_URL=https://alphatrader-api.allternit.com
#   ./scripts/deploy-cloudflare-pages.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Validate required env
if [ -z "${VITE_API_BASE_URL:-}" ]; then
  echo "ERROR: Set VITE_API_BASE_URL to your API origin."
  echo "Example: export VITE_API_BASE_URL=https://alphatrader-api.allternit.com"
  exit 1
fi

if ! command -v npx &> /dev/null; then
  echo "ERROR: npx is required. Install Node.js first."
  exit 1
fi

cd "${PROJECT_ROOT}/web"

echo "Installing dependencies..."
npm ci

echo "Building frontend with API base: ${VITE_API_BASE_URL}"
npm run build

echo "Deploying to Cloudflare Pages..."
npx wrangler pages deploy dist --project-name alphatrader

echo "Done. Dashboard should be live on your Pages domain."
