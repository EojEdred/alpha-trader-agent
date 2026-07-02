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
    msg = """🚦 *DEXTER Execution Commands*

You can now control which accounts Dexter trades using terminal flags:

*Trade ALL Accounts:*
`python3 cli.py run`

*Trade Schwab Only (Options):*
`python3 cli.py run --venue schwab`

*Trade TopstepX Only (Futures):*
`python3 cli.py run --venue topstep`

*Trade OANDA Only (Gold/Forex):*
`python3 cli.py run --venue oanda`

*Custom Multi-Venue:* 
`python3 cli.py run --venue schwab --venue oanda`

💡 *Note:* Add `--dry-run` to any command to simulate trades without spending real money."""
    
    logger.info("Sending Venue Commands to Telegram...")
    result = await send_telegram(message=msg)
    if result.get('status') == 'sent':
        print("✅ Commands sent successfully!")
    else:
        print(f"❌ Failed to send: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(main())