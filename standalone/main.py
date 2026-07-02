#!/usr/bin/env python3
"""
Alpha Trader - Main Entry Point

Usage:
    python main.py                    # Start scheduler
    python main.py --workflow NAME    # Run specific workflow
    python main.py --test             # Run in test mode
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path
from loguru import logger

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from standalone.config import Config
from standalone.scheduler import Scheduler
from standalone.orchestrator import WorkflowOrchestrator
from standalone.health_check import start_health_server, update_health
from tools.telegram_listener import TelegramListener
from tools.profit_locking_engine import sync_state_with_schwab
from dexter.state import get_state, SystemMode

# Configure logging
logger.add("logs/alpha_trader.log", rotation="1 day", retention="30 days")


class AlphaTrader:
    """Main Alpha Trader application."""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = Path(__file__).parent.parent / 'config' / 'config.yaml'
        self.config = Config.load(config_path)
        self.orchestrator = WorkflowOrchestrator(self.config)
        self.scheduler = Scheduler(self.orchestrator, self.config)
        self.telegram = TelegramListener(self)
        self.running = False

    async def start(self):
        """Start the Alpha Trader system."""
        logger.info("Starting Alpha Trader...")
        self.running = True

        state = get_state()
        state.set_mode(SystemMode.STARTING)
        state.add_log("Alpha Trader initializing...")

        # Initialize components
        await self.orchestrator.initialize()

        # Sync position state with Schwab to clear ghost positions
        await sync_state_with_schwab()

        # Start health check server
        start_health_server()
        update_health(status="starting", scheduler_running=False)

        # Start Telegram Listener
        asyncio.create_task(self.telegram.start())

        # Start scheduler
        self.scheduler.start()
        update_health(scheduler_running=True, status="ok")

        state.set_mode(SystemMode.RUNNING)
        state.active_venues = ["Schwab", "OANDA", "TopstepX", "Kalshi"]
        state.add_log(
            f"Alpha Trader scheduler started — jobs: {[j.id for j in self.scheduler.scheduler.get_jobs()]}"
        )
        logger.info("Alpha Trader started successfully")
        logger.info(f"Scheduled jobs: {[j.id for j in self.scheduler.scheduler.get_jobs()]}")

        # Keep running until stopped
        while self.running:
            await asyncio.sleep(1)

    async def stop(self):
        """Stop the Alpha Trader system."""
        logger.info("Stopping Alpha Trader...")
        self.running = False
        self.scheduler.stop()
        await self.telegram.stop()
        await self.orchestrator.shutdown()

        state = get_state()
        state.set_mode(SystemMode.STOPPED)
        state.active_venues = []
        state.add_log("Alpha Trader scheduler stopped")
        logger.info("Alpha Trader stopped")

    async def run_workflow(self, workflow_name: str):
        """Run a specific workflow."""
        await self.orchestrator.initialize()
        logger.info(f"Running workflow: {workflow_name}")
        result = await self.orchestrator.execute_workflow(workflow_name)
        logger.info(f"Workflow {workflow_name} completed: {result.status}")
        return result


async def main():
    parser = argparse.ArgumentParser(description='Alpha Trader')
    parser.add_argument('--config', help='Path to config file')
    parser.add_argument('--workflow', help='Run specific workflow')
    parser.add_argument('--test', action='store_true', help='Test mode')
    parser.add_argument('--list-workflows', action='store_true', help='List available workflows')
    args = parser.parse_args()

    trader = AlphaTrader(args.config)

    if args.list_workflows:
        await trader.orchestrator.initialize()
        print("Available workflows:")
        for wf_id in trader.orchestrator.workflows:
            print(f"  - {wf_id}")
        return

    # Handle shutdown signals
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(trader.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    if args.workflow:
        # Run single workflow
        result = await trader.run_workflow(args.workflow)
        print(f"Result: {result.status}")
    else:
        # Start full system
        await trader.start()


if __name__ == '__main__':
    asyncio.run(main())
