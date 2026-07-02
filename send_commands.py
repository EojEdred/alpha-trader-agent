import asyncio
import os
from dotenv import load_dotenv
from loguru import logger
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from tools.delivery import send_telegram

load_dotenv()

async def main():
    help_text = (
        "🤖 *DEXTER Master Command List*\n\n"
        "*Global Commands:*\n"
        "• `/status` - Check agent health, mode, and uptime.\n"
        "• `/positions` - Get a summary of all positions across all brokers.\n"
        "• `/brief` - Trigger an immediate morning research report.\n"
        "• `/cycle` - Force an immediate scan and reasoning cycle.\n"
        "• `/panic` - *EMERGENCY STOP:* Close all positions and shutdown.\n"
        "• `/help` - Show this command list.\n\n"
        "*Schwab (Options/Equities):*\n"
        "• `/schwab_pos` - View live Schwab positions and P&L.\n"
        "• `/schwab_pdt` - Check your 5-day Day Trade count.\n\n"
        "*TopstepX (Futures):*\n"
        "• `/topstep_pos` - View live NQ/ES positions.\n"
        "• `/topstep_rules` - Check Combine balance and drawdown.\n\n"
        "*OANDA (Forex/Gold):*\n"
        "• `/oanda_pos` - View live XAUUSD positions.\n\n"
        "*Kalshi (Events/Prediction):*\n"
        "• `/kalshi_pos` - View live Kalshi event positions."
    )
    
    logger.info("Sending Master Command List to Telegram...")
    result = await send_telegram(message=help_text)
    if result.get('status') == 'sent':
        print("✅ Command list sent successfully!")
    else:
        print(f"❌ Failed to send list: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())
