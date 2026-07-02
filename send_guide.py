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
    msg = (
        "🤖 *DEXTER Operational Guide*\n\n"
        "*Duration:* Runs indefinitely until stopped (Ctrl+C).\n\n"
        "*Schedule (ET):*\n"
        "• 04:00: Research Cycle\n"
        "• 06:00: Morning Brief (Telegram)\n"
        "• 09:30-16:00: Brain Cycle (Every 5 mins)\n"
        "• 16:30: Self-Reflection & Learning\n\n"
        "*Background Run (tmux):*\n"
        "1. `tmux new -s dexter`\n"
        "2. `python3 cli.py run`\n"
        "3. Press `Ctrl+B` then `D` to detach.\n\n"
        "*Check Status:* `tmux attach -t dexter`"
    )
    
    logger.info("Sending operational guide to Telegram...")
    result = await send_telegram(message=msg)
    if result.get('status') == 'sent':
        print("✅ Guide sent successfully!")
    else:
        print(f"❌ Failed to send guide: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())

