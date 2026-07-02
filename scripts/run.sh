#!/bin/bash
# Run Alpha Trader dashboard manually
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PROJECT_DIR}/venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Run scripts/install.sh first."
    exit 1
fi

source "$VENV_DIR/bin/activate"

export ALPHA_TRADER_AUTO_START="${ALPHA_TRADER_AUTO_START:-true}"
export ALPHA_TRADER_DRY_RUN="${ALPHA_TRADER_DRY_RUN:-false}"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"

echo "Starting Alpha Trader dashboard on http://${HOST}:${PORT}"
python "${PROJECT_DIR}/cli.py" serve --host "$HOST" --port "$PORT"
