"""
Telegram Listener - Interactive Bot Interface

Allows the user to control Dexter via Telegram commands.
"""

import os
import json
import asyncio
import aiohttp
from datetime import datetime
from loguru import logger
from typing import Optional, Dict, Any

class TelegramListener:
    """Long-polling Telegram bot listener."""

    def __init__(self, trader):
        self.trader = trader
        self.token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.offset = 0
        self.running = False
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self):
        """Start the listener loop."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials not fully configured, listener disabled.")
            return

        self.running = True
        self._session = aiohttp.ClientSession()
        logger.info("Telegram Listener started")
        
        # Send a startup message
        await self._send_message("🤖 *Dexter Interactive Mode Active*\nType `/help` for commands.")

        while self.running:
            try:
                await self._poll_updates()
                await asyncio.sleep(2) # Polling interval
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(10)

    async def stop(self):
        """Stop the listener."""
        self.running = False
        if self._session:
            await self._session.close()
        logger.info("Telegram Listener stopped")

    async def _poll_updates(self):
        """Fetch and process new messages."""
        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        params = {"offset": self.offset, "timeout": 30}

        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                return

            data = await resp.json()
            for update in data.get("result", []):
                self.offset = update["update_id"] + 1
                
                message = update.get("message", {})
                text = message.get("text", "")
                from_id = str(message.get("from", {}).get("id", ""))

                # Security check: Only respond to the owner
                if from_id != self.chat_id:
                    logger.warning(f"Unauthorized Telegram access attempt from {from_id}")
                    continue

                if text.startswith("/"):
                    await self._handle_command(text)

    async def _handle_command(self, text: str):
        """Route commands to actions."""
        cmd = text.split()[0].lower()
        logger.info(f"Telegram Command: {cmd}")

        if cmd == "/status":
            await self._cmd_status()
        elif cmd == "/brief":
            await self._cmd_brief()
        elif cmd == "/positions":
            await self._cmd_positions()
        elif cmd == "/schwab_pos":
            await self._cmd_account_pos("schwab")
        elif cmd == "/topstep_pos":
            await self._cmd_account_pos("topstep")
        elif cmd == "/oanda_pos":
            await self._cmd_account_pos("oanda")
        elif cmd == "/kalshi_pos":
            await self._cmd_account_pos("kalshi")
        elif cmd == "/pdt" or cmd == "/schwab_pdt":
            await self._cmd_pdt()
        elif cmd == "/topstep_rules":
            await self._cmd_topstep_rules()
        elif cmd == "/cycle":
            await self._cmd_cycle()
        elif cmd == "/forex_cycle":
            await self._cmd_forex_cycle()
        elif cmd == "/panic":
            await self._cmd_panic()
        elif cmd == "/help":
            await self._cmd_help()
        else:
            await self._send_message(f"Unknown command: {cmd}\nType `/help` for a list.")

    async def _send_message(self, text: str):
        """Helper to send a reply."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                logger.error(f"Failed to send Telegram reply: {await resp.text()}")

    async def _cmd_help(self):
        help_text = (
            "🤖 *Dexter Commands:*\n\n"
            "*Global:*\n"
            "• `/status` - Health & Mode\n"
            "• `/positions` - All accounts summary\n"
            "• `/brief` - Trigger morning report\n"
            "• `/cycle` - Force SPY/QQQ cycle\n"
            "• `/forex_cycle` - Force EUR/USD cycle\n"
            "• `/panic` - KILL SWITCH\n\n"
            "*Schwab (Options):*\n"
            "• `/schwab_pos` - Option positions\n"
            "• `/schwab_pdt` - Day trade count\n\n"
            "*TopstepX (Futures):*\n"
            "• `/topstep_pos` - NQ/ES positions\n"
            "• `/topstep_rules` - Combine risk status\n\n"
            "*OANDA (Forex/Gold):*\n"
            "• `/oanda_pos` - XAUUSD positions\n\n"
            "*Kalshi (Prediction):*\n"
            "• `/kalshi_pos` - Event positions"
        )
        await self._send_message(help_text)

    async def _cmd_status(self):
        uptime = datetime.now().strftime("%H:%M:%S")
        status = (
            "✅ *Dexter Status: ONLINE*\n"
            f"• *Uptime:* {uptime}\n"
            f"• *Scheduler:* Running\n"
            f"• *Mode:* {'DRY RUN' if os.getenv('DRY_RUN') else 'LIVE'}"
        )
        await self._send_message(status)

    async def _cmd_pdt(self):
        from tools.strategy import check_pdt_compliance
        await self._send_message("🔍 Querying Schwab for PDT status...")
        result = await check_pdt_compliance()
        msg = "✅ Within PDT limits." if result else "⚠️ PDT limit reached."
        await self._send_message(msg)

    async def _cmd_topstep_rules(self):
        from tools.topstep import topstep_check_compliance
        await self._send_message("🔍 Querying TopstepX for Combine compliance...")
        result = await topstep_check_compliance()
        if result.get('status') == 'error':
            await self._send_message(f"❌ Error: {result.get('reason')}")
            return
            
        status = "✅ COMPLIANT" if result.get('compliant') else "⚠️ VIOLATION"
        msg = f"*TopstepX Combine Status: {status}*\n"
        msg += f"• Balance: ${result.get('balance'):,.2f}\n"
        msg += f"• Daily P&L: ${result.get('daily_pnl'):,.2f}\n"
        msg += f"• Liquidation Level: ${result.get('drawdown_level'):,.2f}"
        
        if result.get('reasons'):
            msg += f"\n\n*Issues:* {', '.join(result.get('reasons'))}"
        await self._send_message(msg)

    async def _cmd_positions(self):
        from tools.execution import get_all_positions
        await self._send_message("📊 Fetching aggregate positions...")
        pos_list = await get_all_positions()
        
        if not pos_list:
            await self._send_message("Empty portfolio. No open positions.")
            return

        msg = "*Aggregate Positions:*\n"
        for p in pos_list:
            msg += f"• [{p['venue']}] {p['symbol']}: {p['side'].upper()} | P&L: {p['pnl']:+.2f}\n"
        await self._send_message(msg)

    async def _cmd_account_pos(self, venue: str):
        from tools.execution import get_all_positions
        await self._send_message(f"📊 Fetching {venue.upper()} positions...")
        all_pos = await get_all_positions()
        
        # Filter for the specific venue
        pos_list = [p for p in all_pos if p['venue'].lower() == venue.lower()]
        
        if not pos_list:
            await self._send_message(f"No open positions on {venue.upper()}.")
            return

        msg = f"*{venue.upper()} Positions:*\n"
        for p in pos_list:
            msg += f"• {p['symbol']}: {p['side'].upper()} ({p['size']}) | P&L: {p['pnl']:+.2f}\n"
        await self._send_message(msg)

    async def _cmd_brief(self):
        await self._send_message("🌅 Triggering Morning Brief generation...")
        # Add to scheduler queue to run immediately
        self.trader.scheduler.run_now('morning-report-v1')

    async def _cmd_cycle(self):
        await self._send_message("🤖 Forcing an autonomous scan cycle...")
        # We manually trigger the workflow
        asyncio.create_task(self.trader.run_workflow('autonomous-scalper-v1'))

    async def _cmd_forex_cycle(self):
        await self._send_message("💹 Forcing a Forex builder cycle...")
        asyncio.create_task(self.trader.run_workflow('forex-builder-v1'))

    async def _cmd_panic(self):
        await self._send_message("🚨 *PANIC DETECTED!* Initiating emergency shutdown...")
        # 1. Close all positions (T4)
        from tools.execution import get_all_positions, emergency_close
        positions = await get_all_positions()
        for p in positions:
            await emergency_close(symbol=p['symbol'], reason="User initiated PANIC command")
        
        # 2. Stop trader
        asyncio.create_task(self.trader.stop())
        await self._send_message("🛑 All positions closed. Agent shutdown complete.")
