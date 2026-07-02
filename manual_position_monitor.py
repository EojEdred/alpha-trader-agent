import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

from tools.schwab import SchwabClient, schwab_get_option_chain_parsed
from tools.schwab import schwab_place_option_order

ENTRY_PRICE = 1.92
OPTION_SYMBOL = "SPY   260622C00748000"
UNDERLYING = "SPY"
QTY = 1

# Targets / stops
PROFIT_TARGET = 2.30
BREAKEVEN = 1.92
TRAILING_STOP_PCT = 0.20  # 20% trailing from peak
HARD_STOP = 1.54

async def monitor():
    c = SchwabClient()
    highest_mid = ENTRY_PRICE
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring {OPTION_SYMBOL} | entry=${ENTRY_PRICE}")
    print(f"  Profit target: ${PROFIT_TARGET} | Breakeven: ${BREAKEVEN} | Hard stop: ${HARD_STOP}")
    
    while True:
        try:
            # Get current option price
            chain = await schwab_get_option_chain_parsed(UNDERLYING, direction="long")
            strike_data = None
            for s in chain.get('strikes', []):
                if s['strike'] == 748.0:
                    strike_data = s
                    break
            
            if not strike_data:
                print("  Could not get strike data")
                await asyncio.sleep(15)
                continue
            
            bid = strike_data.get('bid', 0)
            ask = strike_data.get('ask', 0)
            mid = round((bid + ask) / 2, 2)
            last = strike_data.get('last', mid)
            
            highest_mid = max(highest_mid, mid)
            trailing_stop = round(highest_mid * (1 - TRAILING_STOP_PCT), 2)
            
            unrealized = round((mid - ENTRY_PRICE) * 100 * QTY, 2)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SPY={chain.get('underlying_price')} | 748C bid=${bid} ask=${ask} mid=${mid} | P&L=${unrealized} | peak=${highest_mid} | trail_stop=${trailing_stop}")
            
            # Check if profit target hit
            if bid >= PROFIT_TARGET:
                print(f"  🎯 Profit target reached. Sell order at ${PROFIT_TARGET} should fill.")
                # Check if existing sell order still working
                hashes = await c.get_account_numbers()
                h = hashes[0]
                resp = c.client.get_orders_for_account(h, status="WORKING")
                orders = resp.json()
                sell_order_working = any(
                    o['orderLegCollection'][0]['instrument']['symbol'] == OPTION_SYMBOL 
                    and o['orderLegCollection'][0]['instruction'] == 'SELL_TO_CLOSE'
                    for o in orders
                )
                if not sell_order_working:
                    print("  No working sell order — placing market sell to lock profit")
                    await schwab_place_option_order(
                        symbol=OPTION_SYMBOL,
                        quantity=QTY,
                        side="sell_to_close",
                        order_type="MARKET"
                    )
                break
            
            # Check hard stop
            if ask <= HARD_STOP:
                print(f"  🛑 HARD STOP hit at ${HARD_STOP}. Selling at market.")
                await schwab_place_option_order(
                    symbol=OPTION_SYMBOL,
                    quantity=QTY,
                    side="sell_to_close",
                    order_type="MARKET"
                )
                break
            
            # Check trailing stop (only if we're up at least $15)
            if highest_mid > ENTRY_PRICE and mid <= trailing_stop and unrealized >= 15:
                print(f"  🛑 Trailing stop hit at ${trailing_stop} (peak ${highest_mid}). Selling at market.")
                await schwab_place_option_order(
                    symbol=OPTION_SYMBOL,
                    quantity=QTY,
                    side="sell_to_close",
                    order_type="MARKET"
                )
                break
            
            await asyncio.sleep(15)
            
        except Exception as e:
            print(f"  Error: {e}")
            await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(monitor())
