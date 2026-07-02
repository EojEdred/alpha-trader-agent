#!/bin/bash
# Alpha Trader Daemon Starter
# Usage: ./scripts/start_daemon.sh
# This script starts the Alpha Trader in a persistent background process.

set -e

PROJECT_DIR="/Users/macbook/Desktop/allternit-workspace/allternit-alpha-trader-agent"
VENV_PATH="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"
PIDFILE="$PROJECT_DIR/.alpha-trader.pid"

cd "$PROJECT_DIR"

# Activate virtual environment
source "$VENV_PATH/bin/activate"

# Ensure log directory exists
mkdir -p "$LOG_DIR"

# Set Python path
export PYTHONPATH="$PROJECT_DIR"

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
fi

echo "Starting Alpha Trader daemon..."
echo "Project: $PROJECT_DIR"
echo "Log dir: $LOG_DIR"
echo "PID file: $PIDFILE"

# Check if already running
if [ -f "$PIDFILE" ]; then
    OLD_PID=$(cat "$PIDFILE")
    if ps -p "$OLD_PID" > /dev/null 2>&1; then
        echo "Alpha Trader is already running (PID: $OLD_PID)"
        echo "To restart: kill $OLD_PID && ./scripts/start_daemon.sh"
        exit 1
    else
        echo "Removing stale PID file..."
        rm "$PIDFILE"
    fi
fi

# Start the daemon
nohup "$VENV_PATH/bin/python" -m standalone.main > "$LOG_DIR/daemon.out" 2>&1 &
NEW_PID=$!
echo $NEW_PID > "$PIDFILE"

echo "Alpha Trader started with PID: $NEW_PID"
echo "Logs: tail -f $LOG_DIR/daemon.out"
echo ""
echo "To stop: kill $(cat $PIDFILE)"
echo "To check health: curl http://localhost:8765/health"
