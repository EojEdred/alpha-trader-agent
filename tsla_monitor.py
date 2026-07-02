import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

from tools.schwab import SchwabClient, schwab_get_option_chain_parsed, schwab_place_option_order
from tools.delivery import send_telegram

# Trade parameters
OPTION_SYMBOL = "TSLA  260626C00405000"
UNDERLYING = "TSLA"
STRIKE = 405.0
QTY = 1
ENTRY_PRICE = 8.35

# Risk management
HARD_STOP_PCT = 0.10
HARD_STOP_PRICE = round(ENTRY_PRICE * (1 - HARD_STOP_PCT), 2)
BREAKEVEN_TRIGGER_PCT = 0.15
BREAKEVEN_PRICE = ENTRY_PRICE
TRAILING_TRIGGER_PCT = 0.30
TRAILING_STOP_PCT = 0.25

# Alert levels (notify but don't sell)
ALERT_LEVELS = [0.25, 0.50, 1.00, 1.50, 2.00]

async def notify(message: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    await send_telegram(message=message)

async def monitor():
    c = SchwabClient()
    print(f"Monitoring {OPTION_SYMBOL} | entry=${ENTRY_PRICE} | hard_stop=${HARD_STOP_PRICE}")
    print(f"Alert levels: {', '.join(f'+{int(l*100)}%' for l in ALERT_LEVELS)}")
    
    await notify(
        f"🔔 *TSLA Position Active*\n"
        f"Contract: `{OPTION_SYMBOL}`\n"
        f"Entry: ${ENTRY_PRICE}\n"
        f"Hard stop: ${HARD_STOP_PRICE} (-10%)\n"
        f"Trailing stop activates at +30%\n"
        f"I will alert at +25%, +50%, +100%, +150%, +200%"
    )
    
    highest_mid = ENTRY_PRICE
    breakeven_activated = False
    trailing_activated = False
    trailing_stop = HARD_STOP_PRICE
    alerts_sent = set()
    
    while True:
        try:
            chain = await schwab_get_option_chain_parsed(UNDERLYING, direction="long")
            strike_data = None
            for s in chain.get('strikes', []):
                if s['strike'] == STRIKE:
                    strike_data = s
                    break
            
            if not strike_data:
                print("  Could not get strike data")
                await asyncio.sleep(15)
                continue
            
            bid = float(strike_data.get('bid', 0))
            ask = float(strike_data.get('ask', 0))
            mid = round((bid + ask) / 2, 2)
            last = float(strike_data.get('last', mid))
            
            highest_mid = max(highest_mid, mid)
            unrealized_pct = round((mid - ENTRY_PRICE) / ENTRY_PRICE, 3)
            unrealized_dollars = round((mid - ENTRY_PRICE) * 100 * QTY, 2)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] TSLA={chain.get('underlying_price')} | 410C bid=${bid} ask=${ask} mid=${mid} | P&L={unrealized_pct:+.1%} (${unrealized_dollars}) | peak=${highest_mid}")
            
            # Alert levels
            for level in ALERT_LEVELS:
                if unrealized_pct >= level and level not in alerts_sent:
                    target_price = round(ENTRY_PRICE * (1 + level), 2)
                    await notify(
                        f"🚀 *TSLA up +{int(level*100)}%*\n"
                        f"Current mid: ${mid}\n"
                        f"Unrealized: ${unrealized_dollars}\n"
                        f"Tell me to sell or let it run."
                    )
                    alerts_sent.add(level)
            
            # Activate breakeven stop after +15%
            if not breakeven_activated and unrealized_pct >= BREAKEVEN_TRIGGER_PCT:
                breakeven_activated = True
                trailing_stop = max(trailing_stop, BREAKEVEN_PRICE)
                await notify(f"🛡️ *TSLA stop moved to breakeven* ${BREAKEVEN_PRICE}")
            
            # Activate trailing stop after +30%
            if not trailing_activated and unrealized_pct >= TRAILING_TRIGGER_PCT:
                trailing_activated = True
                await notify(f"🎯 *TSLA trailing stop activated* — will sell if it drops {TRAILING_STOP_PCT*100:.0f}% from peak ${highest_mid}")
            
            if trailing_activated:
                trailing_stop = max(trailing_stop, round(highest_mid * (1 - TRAILING_STOP_PCT), 2))
            
            # Check hard stop / trailing stop
            sell_trigger = None
            if ask <= HARD_STOP_PRICE and not (breakeven_activated or trailing_activated):
                sell_trigger = f"hard stop ${HARD_STOP_PRICE}"
            elif trailing_activated and mid <= trailing_stop:
                sell_trigger = f"trailing stop ${trailing_stop}"
            
            if sell_trigger:
                await notify(f"🛑 *TSLA {sell_trigger} hit* — selling at market")
                result = await schwab_place_option_order(
                    symbol=OPTION_SYMBOL,
                    quantity=QTY,
                    side="sell_to_close",
                    order_type="MARKET"
                )
                if result.get('status') == 'submitted':
                    await notify(f"✅ *TSLA sold at market*\nExit P&L: ${unrealized_dollars}")
                else:
                    await notify(f"❌ *TSLA sell failed:* {result.get('error')}")
                break
            
            await asyncio.sleep(15)
            
        except Exception as e:
            print(f"  Error: {e}")
            await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(monitor())
