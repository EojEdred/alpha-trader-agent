import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

from tools.schwab import SchwabClient, schwab_get_option_chain_parsed, schwab_place_option_order
from tools.delivery import send_trade_alert


async def wait_for_fill(client: SchwabClient, order_id: str, account_hash: str, timeout: int = 60):
    """Wait for an order to fill."""
    for _ in range(timeout // 5):
        try:
            status = await client.get_order_status(order_id)
            if status.get('status') == 'FILLED':
                return status
            print(f"  Order {order_id}: {status.get('status')}, filled={status.get('filledQuantity')}")
        except Exception as e:
            print(f"  Error checking order: {e}")
        await asyncio.sleep(5)
    return None


async def verify_position(client: SchwabClient, option_symbol: str):
    """Verify we actually own the option."""
    positions = await client.get_positions()
    for p in positions:
        if p.get('asset_type') == 'OPTION' and p.get('option_symbol') == option_symbol:
            return p
    return None


async def execute_directional_trade(
    option_symbol: str,
    underlying: str,
    strike: float,
    direction: str,
    quantity: int,
    entry_price: float,
    hard_stop_pct: float = 0.10,
    trailing_trigger_pct: float = 0.30,
    trailing_stop_pct: float = 0.25,
    alert_levels: list = None,
):
    """
    Execute a directional option trade with proper fill verification and monitoring.
    """
    if alert_levels is None:
        alert_levels = [0.50, 1.00]
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Placing order: {option_symbol} x{quantity} @ ${entry_price}")
    
    # Place limit buy
    buy_result = await schwab_place_option_order(
        symbol=option_symbol,
        quantity=quantity,
        side="buy_to_open",
        order_type="LIMIT",
        price=entry_price
    )
    
    if buy_result.get('status') != 'submitted':
        print(f"Buy order failed: {buy_result}")
        await send_trade_alert(f"❌ Buy order failed for {option_symbol}: {buy_result.get('error', 'unknown')}")
        return
    
    order_id = buy_result['order_id']
    client = SchwabClient()
    hashes = await client.get_account_numbers()
    account_hash = hashes[0]
    
    print(f"Buy order submitted: {order_id}. Waiting for fill...")
    fill = await wait_for_fill(client, order_id, account_hash)
    
    if not fill:
        print("Order did not fill within timeout. Canceling...")
        try:
            client.client.cancel_order(order_id, account_hash)
        except Exception:
            pass
        await send_trade_alert(f"⚠️ {option_symbol} order did not fill and was canceled")
        return
    
    # Verify position exists
    position = await verify_position(client, option_symbol)
    if not position:
        print("Order reported fill but position not found. Aborting monitor.")
        await send_trade_alert(f"⚠️ {option_symbol} fill reported but no position found")
        return
    
    actual_entry = float(fill['orderActivityCollection'][0]['executionLegs'][0]['price'])
    print(f"Filled at ${actual_entry}")
    
    # Send entry alert
    await send_trade_alert(
        f"🚀 *Trade Entered*\n"
        f"Contract: `{option_symbol}`\n"
        f"Qty: {quantity} | Entry: ${actual_entry}\n"
        f"Hard stop: ${round(actual_entry * (1 - hard_stop_pct), 2)} ({int(hard_stop_pct*100)}%)\n"
        f"Trailing stop activates at +{int(trailing_trigger_pct*100)}%"
    )
    
    # Start monitoring
    await monitor_position(
        client=client,
        option_symbol=option_symbol,
        underlying=underlying,
        strike=strike,
        direction=direction,
        quantity=quantity,
        entry_price=actual_entry,
        hard_stop_pct=hard_stop_pct,
        trailing_trigger_pct=trailing_trigger_pct,
        trailing_stop_pct=trailing_stop_pct,
        alert_levels=alert_levels,
    )


async def monitor_position(
    client: SchwabClient,
    option_symbol: str,
    underlying: str,
    strike: float,
    direction: str,
    quantity: int,
    entry_price: float,
    hard_stop_pct: float,
    trailing_trigger_pct: float,
    trailing_stop_pct: float,
    alert_levels: list,
):
    """Monitor an open option position."""
    hard_stop_price = round(entry_price * (1 - hard_stop_pct), 2)
    breakeven_trigger = round(entry_price * (1 + 0.15), 2)
    trailing_trigger = round(entry_price * (1 + trailing_trigger_pct), 2)
    
    highest_mid = entry_price
    breakeven_activated = False
    trailing_activated = False
    trailing_stop = hard_stop_price
    alerts_sent = set()
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Monitoring {option_symbol} | entry=${entry_price} | hard_stop=${hard_stop_price}")
    
    while True:
        try:
            opt_direction = "long" if direction == "CALL" else "short"
            chain = await schwab_get_option_chain_parsed(underlying, direction=opt_direction)
            strike_data = None
            for s in chain.get('strikes', []):
                if s['strike'] == strike:
                    strike_data = s
                    break
            
            if not strike_data:
                await asyncio.sleep(15)
                continue
            
            bid = float(strike_data.get('bid', 0))
            ask = float(strike_data.get('ask', 0))
            mid = round((bid + ask) / 2, 2)
            
            highest_mid = max(highest_mid, mid)
            unrealized_pct = round((mid - entry_price) / entry_price, 3)
            unrealized_dollars = round((mid - entry_price) * 100 * quantity, 2)
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {underlying}={chain.get('underlying_price')} | {strike}C bid=${bid} ask=${ask} mid=${mid} | P&L={unrealized_pct:+.1%} (${unrealized_dollars}) | peak=${highest_mid}")
            
            # Alert levels
            for level in alert_levels:
                if unrealized_pct >= level and level not in alerts_sent:
                    await send_trade_alert(
                        f"🚀 *{underlying} option up +{int(level*100)}%*\n"
                        f"Contract: `{option_symbol}`\n"
                        f"Current mid: ${mid}\n"
                        f"Unrealized: ${unrealized_dollars}\n"
                        f"Reply SELL to exit or HOLD to let it run."
                    )
                    alerts_sent.add(level)
            
            # Breakeven stop
            if not breakeven_activated and mid >= breakeven_trigger:
                breakeven_activated = True
                trailing_stop = max(trailing_stop, entry_price)
                await send_trade_alert(f"🛡️ *{option_symbol} stop moved to breakeven* ${entry_price}")
            
            # Trailing stop
            if not trailing_activated and mid >= trailing_trigger:
                trailing_activated = True
                await send_trade_alert(f"🎯 *{option_symbol} trailing stop activated* — selling if it drops {trailing_stop_pct*100:.0f}% from peak ${highest_mid}")
            
            if trailing_activated:
                trailing_stop = max(trailing_stop, round(highest_mid * (1 - trailing_stop_pct), 2))
            
            # Check stops
            sell_trigger = None
            if not (breakeven_activated or trailing_activated) and ask <= hard_stop_price:
                sell_trigger = f"hard stop ${hard_stop_price}"
            elif trailing_activated and mid <= trailing_stop:
                sell_trigger = f"trailing stop ${trailing_stop}"
            
            if sell_trigger:
                await send_trade_alert(f"🛑 *{option_symbol} {sell_trigger} hit* — selling at market")
                result = await schwab_place_option_order(
                    symbol=option_symbol,
                    quantity=quantity,
                    side="sell_to_close",
                    order_type="MARKET"
                )
                if result.get('status') == 'submitted':
                    await send_trade_alert(f"✅ *{option_symbol} sold at market*\nExit P&L: ${unrealized_dollars}")
                else:
                    await send_trade_alert(f"❌ *{option_symbol} sell failed:* {result.get('error')}")
                break
            
            await asyncio.sleep(15)
        except Exception as e:
            print(f"Monitor error: {e}")
            await asyncio.sleep(15)


if __name__ == "__main__":
    # Example usage
    asyncio.run(execute_directional_trade(
        option_symbol="TSLA  260626C00405000",
        underlying="TSLA",
        strike=405.0,
        direction="CALL",
        quantity=1,
        entry_price=8.35,
    ))
