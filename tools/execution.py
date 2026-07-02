"""
Execution Tools - Order management and trade execution

Implements:
- submit_order
- modify_order
- cancel_order
- emergency_close
- get_positions
- get_order_status
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger

# IB connection (when available)
IB_CLIENT = None


async def connect_ib(host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
    """Connect to Interactive Brokers."""
    global IB_CLIENT
    try:
        from ib_insync import IB
        IB_CLIENT = IB()
        await IB_CLIENT.connectAsync(host, port, client_id)
        logger.info(f"Connected to IB at {host}:{port}")
        return True
    except Exception as e:
        logger.warning(f"IB connection failed: {e}")
        return False


async def submit_order(
    symbol: str,
    side: str,
    quantity: int,
    order_type: str = "limit",
    limit_price: float = None,
    stop_price: float = None,
    time_in_force: str = "day",
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Submit an order to the broker.

    This is a T3 tool - requires confirmation in production.
    """
    logger.info(f"Submitting order: {side} {quantity} {symbol} @ {limit_price or 'market'}")

    result = {
        'order_id': None,
        'status': 'pending',
        'symbol': symbol,
        'side': side,
        'quantity': quantity,
        'order_type': order_type,
        'limit_price': limit_price,
        'submitted_at': datetime.utcnow().isoformat()
    }

    # Check if IB is connected
    if IB_CLIENT and IB_CLIENT.isConnected():
        try:
            from ib_insync import Stock, MarketOrder, LimitOrder

            contract = Stock(symbol, 'SMART', 'USD')
            await IB_CLIENT.qualifyContractsAsync(contract)

            if order_type == 'market':
                order = MarketOrder(side.upper(), quantity)
            else:
                order = LimitOrder(side.upper(), quantity, limit_price)

            trade = IB_CLIENT.placeOrder(contract, order)

            result['order_id'] = str(trade.order.orderId)
            result['status'] = trade.orderStatus.status

        except Exception as e:
            logger.error(f"Order submission failed: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
    else:
        # Paper trading / simulation mode
        import uuid
        result['order_id'] = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        result['status'] = 'simulated'
        logger.warning("Order simulated (IB not connected)")

    return result


async def modify_order(
    order_id: str,
    new_quantity: int = None,
    new_limit_price: float = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Modify an existing order.
    """
    logger.info(f"Modifying order {order_id}")

    result = {
        'order_id': order_id,
        'status': 'modified',
        'new_quantity': new_quantity,
        'new_limit_price': new_limit_price,
        'modified_at': datetime.utcnow().isoformat()
    }

    # Implement IB order modification
    if IB_CLIENT and IB_CLIENT.isConnected():
        # Find and modify order
        pass

    return result


async def cancel_order(
    order_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Cancel an existing order.
    """
    logger.info(f"Cancelling order {order_id}")

    result = {
        'order_id': order_id,
        'status': 'cancelled',
        'cancelled_at': datetime.utcnow().isoformat()
    }

    if IB_CLIENT and IB_CLIENT.isConnected():
        # Find and cancel order
        pass

    return result


async def emergency_close(
    symbol: str,
    reason: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Emergency position close - T4 tool, no confirmation required.

    This is a circuit breaker action that closes a position immediately.
    """
    logger.warning(f"EMERGENCY CLOSE: {symbol} - Reason: {reason}")

    result = {
        'symbol': symbol,
        'reason': reason,
        'status': 'executed',
        'executed_at': datetime.utcnow().isoformat()
    }

    if IB_CLIENT and IB_CLIENT.isConnected():
        try:
            from ib_insync import Stock, MarketOrder

            # Get current position
            positions = IB_CLIENT.positions()
            position = next((p for p in positions if p.contract.symbol == symbol), None)

            if position and position.position != 0:
                contract = Stock(symbol, 'SMART', 'USD')
                await IB_CLIENT.qualifyContractsAsync(contract)

                # Close with market order
                side = 'SELL' if position.position > 0 else 'BUY'
                quantity = abs(position.position)
                order = MarketOrder(side, quantity)

                trade = IB_CLIENT.placeOrder(contract, order)
                result['order_id'] = str(trade.order.orderId)
                result['quantity_closed'] = quantity

        except Exception as e:
            logger.error(f"Emergency close failed: {e}")
            result['status'] = 'failed'
            result['error'] = str(e)
    else:
        result['status'] = 'simulated'
        logger.warning("Emergency close simulated (IB not connected)")

    return result


async def get_positions(
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get current positions from broker.
    """
    logger.info("Fetching positions")

    result = {
        'positions': [],
        'total_value': 0.0,
        'timestamp': datetime.utcnow().isoformat()
    }

    if IB_CLIENT and IB_CLIENT.isConnected():
        try:
            positions = IB_CLIENT.positions()
            for p in positions:
                pos = {
                    'symbol': p.contract.symbol,
                    'quantity': p.position,
                    'avg_cost': p.avgCost,
                    'market_value': p.position * p.avgCost,  # Approximate
                }
                result['positions'].append(pos)
                result['total_value'] += pos['market_value']

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            result['error'] = str(e)

    return result


async def get_order_status(
    order_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Get status of an order.
    """
    logger.info(f"Getting status for order {order_id}")

    result = {
        'order_id': order_id,
        'status': 'unknown',
        'filled_qty': 0,
        'remaining_qty': 0,
        'avg_fill_price': 0.0,
        'timestamp': datetime.utcnow().isoformat()
    }

    if IB_CLIENT and IB_CLIENT.isConnected():
        # Query order status
        pass

    return result


def validate_trade(
    trade_request: Dict,
    **kwargs
) -> Dict[str, Any]:
    """
    Validate trade parameters before submission.
    """
    logger.info("Validating trade")

    result = {
        'valid': True,
        'errors': [],
        'validated_trade': trade_request,
        'timestamp': datetime.utcnow().isoformat()
    }

    # Check required fields
    required = ['symbol', 'side', 'quantity']
    for field in required:
        if field not in trade_request:
            result['valid'] = False
            result['errors'].append(f"Missing required field: {field}")

    # Validate side
    if trade_request.get('side') not in ['buy', 'sell', 'BUY', 'SELL']:
        result['valid'] = False
        result['errors'].append("Invalid side (must be 'buy' or 'sell')")

    # Validate quantity
    qty = trade_request.get('quantity', 0)
    if not isinstance(qty, int) or qty <= 0:
        result['valid'] = False
        result['errors'].append("Quantity must be positive integer")

    return result


def verify_fill_quality(
    fill_result: Dict,
    risk_approved_trade: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze execution quality.
    """
    logger.info("Verifying fill quality")

    result = {
        'slippage': 0.0,
        'slippage_pct': 0.0,
        'execution_score': 1.0,  # 1.0 = perfect
        'timestamp': datetime.utcnow().isoformat()
    }

    if fill_result and risk_approved_trade:
        expected_price = risk_approved_trade.get('limit_price', 0)
        actual_price = fill_result.get('avg_fill_price', expected_price)

        if expected_price > 0:
            result['slippage'] = actual_price - expected_price
            result['slippage_pct'] = (result['slippage'] / expected_price) * 100

            # Score based on slippage (0.1% = 0.9 score, 1% = 0 score)
            result['execution_score'] = max(0, 1 - abs(result['slippage_pct']) / 1.0)

    return result


def evaluate_stops(
    current_positions: List[Dict],
    current_prices: Dict,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluate stop conditions and expiration guardrails for positions.
    """
    logger.info("Evaluating stop conditions")

    result = {
        'stop_triggers': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    # 1. EXPIRATION GUARDRAIL (AUTO-EXIT)
    # If we are holding an option that expires TODAY, we must close it.
    for pos in current_positions:
        symbol = pos.get('symbol', '')
        # Schwab option symbols usually contain the expiration date: SPY   260105P...
        # We also check if it's 0 DTE from metadata if available
        
        is_option = len(symbol) > 10 or ' ' in symbol
        if is_option:
            # Check for today's date in symbol or DTE < 1
            today_str = datetime.utcnow().strftime('%y%m%d') # YYMMDD format
            if today_str in symbol:
                logger.warning(f"🚨 EXPIRATION ALERT: {symbol} expires today. Triggering auto-exit to avoid exercise.")
                result['stop_triggers'].append({
                    'symbol': symbol,
                    'reason': 'Auto-exit (0 DTE Guardrail)',
                    'action': 'emergency_close'
                })

    return result


def evaluate_alerts(
    current_prices: Dict,
    alert_config: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluate price alert conditions.
    """
    result = {
        'triggered_alerts': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    return result


async def submit_trade(
    symbol: str = None,
    direction: str = None,
    size: float = None,
    venue: str = "auto",
    selected_trade: Dict = None,
    **kwargs
) -> Dict:
    """
    Submit a trade using the A+ scoring system and appropriate venue.
    """
    # Extract from selected_trade if provided
    if selected_trade:
        symbol = symbol or selected_trade.get('symbol')
        direction = direction or selected_trade.get('direction')
        kwargs['trade_type'] = kwargs.get('trade_type') or selected_trade.get('trade_type')

    from tools.scoring import score_setup
    from tools.strategy import check_pdt_compliance

    logger.info(f"Submitting trade: {direction} {symbol} on {venue}")

    # 1. PDT Guardrail Check
    trade_type = kwargs.get('trade_type', 'intraday')
    if not await check_pdt_compliance() and trade_type == 'intraday':
        logger.warning(f"Trade rejected: PDT limit reached and trade type is {trade_type}")
        return {
            'status': 'rejected',
            'reason': 'PDT limit reached'
        }

    # 1b. Check for Dry Run mode
    import os
    is_dry_run = os.getenv("DRY_RUN", "false").lower() == "true"
    if is_dry_run:
        logger.info(f"🧪 DRY RUN: Simulating {direction} trade for {symbol} on {venue}")
        
        # Notify via Telegram
        from tools.delivery import send_telegram
        import asyncio
        msg = f"🧪 *DRY RUN EXECUTION*\n"
        msg += f"*Symbol:* {symbol}\n"
        msg += f"*Action:* {direction.upper()}\n"
        msg += f"*Venue:* {venue}\n"
        msg += "_No real orders were placed._"
        asyncio.create_task(send_telegram(message=msg))
        
        return {
            'status': 'simulated',
            'symbol': symbol,
            'direction': direction,
            'venue': venue,
            'timestamp': datetime.utcnow().isoformat()
        }

    # 2. Score the setup
    score_result = await score_setup(symbol)

    if not score_result.trade_allowed:
        return {
            'status': 'rejected',
            'reason': 'Setup did not meet minimum criteria',
            'score': score_result.total,
            'grade': score_result.grade.value
        }

    # Determine size if not provided
    if size is None:
        # Use scoring system to determine size
        size = 1000 * score_result.size_modifier  # Base size * modifier

    # Determine execution venue based on symbol and preferences
    if venue == "auto":
        if symbol.upper() in ["XAUUSD", "GOLD", "GC", "XAU"]:
            venue = "oanda"
        elif any(x in symbol.upper() for x in ["SPY", "QQQ", "IWM", "DIA"]):
            venue = "schwab"
        elif any(x in symbol.upper() for x in ["NQ", "ES", "CL"]):
            venue = "topstep"
        elif len(symbol) <= 6 and not any(x in symbol.upper() for x in ["SPY", "QQQ", "IWM", "DIA"]):
            # Likely a prediction market
            venue = "kalshi"
        else:
            venue = "polymarket"  # Default to polymarket for other cases

    # Execute trade based on venue
    if venue == "oanda":
        from tools.oanda import oanda_place_order
        result = await oanda_place_order(
            instrument=symbol.replace("/", "_").upper(),
            units=int(size),
            side=direction
        )
    elif venue == "schwab":
        from tools.schwab import schwab_place_order, get_schwab_client
        
        # If trading SPY or QQQ, switch to options
        if symbol.upper() in ["SPY", "QQQ"]:
            from tools.strategy import select_best_option_contract
            option_symbol = await select_best_option_contract(symbol.upper(), direction, trade_type)
            
            if option_symbol:
                logger.info(f"Agent executing OPTION trade for {symbol}: {option_symbol}")
                client = get_schwab_client()
                # 1 contract = 100 shares, so adjust size
                option_size = max(1, int(size / 100)) 
                result = await client.place_option_order(
                    symbol=option_symbol,
                    quantity=option_size,
                    side="buy_to_open"
                )
            else:
                return {'status': 'error', 'reason': 'Could not find liquid option contract'}
        else:
            result = await schwab_place_order(
                symbol=symbol.upper(),
                quantity=int(size),
                side=direction
            )
    elif venue == "topstep":
        from tools.topstep import topstep_place_order
        result = await topstep_place_order(
            symbol=symbol.upper(),
            quantity=int(size),
            side=direction,
            confirmed=kwargs.get("confirmed", False),
        )
    elif venue == "kalshi":
        from tools.kalshi import place_order
        # For Kalshi, we need to determine if it's a yes/no market
        # For now, assume 'long' means 'yes' and 'short' means 'no'
        side = "yes" if direction == "long" else "no"
        result = await place_order(
            ticker=symbol,
            side=side,
            size=int(size),
            price=0.5  # Default price
        )
    elif venue == "polymarket":
        from tools.polymarket import place_order
        result = await place_order(
            symbol=symbol,
            side=direction,
            size=size,
            price=0.5  # Default price
        )
    elif venue == "prizepicks":
        from tools.prizepicks import prizepicks_place_entry
        # For PrizePicks, we need to format the entry properly
        selections = [{"player": symbol, "direction": direction}]
        result = await prizepicks_place_entry(
            contest_id="default_contest",  # Would need to fetch actual contest ID
            player_selections=selections
        )
    elif venue == "betmgm":
        from tools.betmgm import betmgm_place_bet
        bet_data = {
            "event": symbol,
            "selection": direction,
            "stake": size
        }
        result = await betmgm_place_bet(bet_data=bet_data)
    elif venue == "fanduel":
        from tools.fanduel import fanduel_place_bet
        bet_data = {
            "event": symbol,
            "selection": direction,
            "stake": size
        }
        result = await fanduel_place_bet(bet_data=bet_data)
    elif venue == "pandafx":
        from tools.pandafx import pandafx_place_trade
        result = await pandafx_place_trade(
            pair=symbol,
            side=direction,
            amount=size,
            order_type="MARKET"
        )
    elif venue == "apexfutures":
        from tools.apexfutures import apexfutures_place_trade
        result = await apexfutures_place_trade(
            symbol=symbol,
            side=direction,
            quantity=int(size),
            order_type="MARKET"
        )
    else:
        return {
            'status': 'error',
            'reason': f'Unknown venue: {venue}'
        }

    # Notify via Telegram for LIVE trades
    if result.get('status') in ['filled', 'submitted']:
        from tools.delivery import send_telegram
        import asyncio
        msg = f"🚀 *LIVE TRADE EXECUTED*\n"
        msg += f"*Symbol:* {symbol}\n"
        msg += f"*Action:* {direction.upper()}\n"
        msg += f"*Venue:* {venue}\n"
        msg += f"*Status:* {result.get('status')}\n"
        msg += f"*Order ID:* {result.get('order_id')}"
        asyncio.create_task(send_telegram(message=msg))

    return result


async def _normalize_schwab_positions(positions: List[Dict]) -> List[Dict]:
    """Normalize Schwab position dicts to the dashboard schema."""
    from tools.schwab import schwab_get_price

    normalized = []
    for pos in positions:
        try:
            quantity = float(pos.get("quantity", 0))
            size = abs(quantity)
            side = "long" if quantity > 0 else "short" if quantity < 0 else pos.get("side", "")
            symbol = pos.get("symbol") or pos.get("option_symbol") or "unknown"
            entry = pos.get("average_price", 0)
            market_price = pos.get("market_price", 0)

            if not market_price and symbol and not symbol.startswith("SPY   "):
                try:
                    quote = await schwab_get_price(symbol)
                    market_price = quote.get("last") or quote.get("bid") or quote.get("ask") or 0
                except Exception as e:
                    logger.debug(f"Could not fetch Schwab quote for {symbol}: {e}")

            normalized.append({
                "venue": "Schwab",
                "symbol": symbol,
                "side": side,
                "size": size,
                "quantity": quantity,
                "entry": entry,
                "market_price": market_price,
                "pnl": pos.get("unrealized_pl", 0),
                "market_value": pos.get("market_value", 0),
                "asset_type": pos.get("asset_type", ""),
                "option_type": pos.get("option_type", ""),
                "strike": pos.get("strike", 0),
                "expiration": pos.get("expiration", ""),
                "days_to_expiration": pos.get("days_to_expiration"),
            })
        except Exception as e:
            logger.error(f"Error normalizing Schwab position {pos}: {e}")
    return normalized


async def _normalize_oanda_positions(positions: List[Dict]) -> List[Dict]:
    """Normalize OANDA position dicts to the dashboard schema."""
    from tools.oanda import oanda_get_price

    normalized = []
    for pos in positions:
        try:
            symbol = pos.get("symbol", "")
            market_price = pos.get("current", 0)
            if not market_price and symbol:
                try:
                    quote = await oanda_get_price(symbol)
                    market_price = (quote.get("bid", 0) + quote.get("ask", 0)) / 2
                except Exception as e:
                    logger.debug(f"Could not fetch OANDA quote for {symbol}: {e}")

            normalized.append({
                "venue": pos.get("venue", "OANDA"),
                "symbol": symbol,
                "side": pos.get("side", ""),
                "size": pos.get("size", 0),
                "quantity": pos.get("size", 0) * (1 if pos.get("side") == "long" else -1),
                "entry": pos.get("entry", 0),
                "market_price": market_price,
                "pnl": pos.get("pnl", 0),
            })
        except Exception as e:
            logger.error(f"Error normalizing OANDA position {pos}: {e}")
    return normalized


async def get_all_positions() -> Dict[str, Any]:
    """
    Get positions from all connected venues.

    Returns:
        Dict with keys: positions (List[Dict]), total_value (float), timestamp (str)
    """
    logger.info("Fetching positions from all venues")

    all_positions: List[Dict] = []

    # Get Schwab positions
    try:
        from tools.schwab import schwab_get_positions
        schwab_positions = await schwab_get_positions()
        all_positions.extend(await _normalize_schwab_positions(schwab_positions))
    except Exception as e:
        logger.error(f"Error fetching Schwab positions: {e}")

    # Get OANDA positions
    try:
        from tools.oanda import oanda_get_positions
        oanda_positions = await oanda_get_positions()
        all_positions.extend(await _normalize_oanda_positions(oanda_positions))
    except Exception as e:
        logger.error(f"Error fetching OANDA positions: {e}")

    # Get TopstepX positions
    try:
        from tools.topstep import topstep_get_positions
        ts_positions = await topstep_get_positions()
        all_positions.extend(ts_positions)
    except Exception as e:
        logger.error(f"Error fetching TopstepX positions: {e}")

    # Get Kalshi positions
    try:
        from tools.kalshi import kalshi_get_positions
        kalshi_positions = await kalshi_get_positions()
        all_positions.extend(kalshi_positions)
    except Exception as e:
        logger.error(f"Error fetching Kalshi positions: {e}")

    # Get Polymarket positions
    try:
        from tools.polymarket import polymarket_get_positions
        poly_positions = await polymarket_get_positions()
        all_positions.extend(poly_positions)
    except Exception as e:
        logger.error(f"Error fetching Polymarket positions: {e}")

    # Get PrizePicks positions
    try:
        from tools.prizepicks import prizepicks_get_positions
        pp_positions = await prizepicks_get_positions()
        all_positions.extend(pp_positions)
    except Exception as e:
        logger.error(f"Error fetching PrizePicks positions: {e}")

    # Get BetMGM positions
    try:
        from tools.betmgm import betmgm_get_positions
        bm_positions = await betmgm_get_positions()
        all_positions.extend(bm_positions)
    except Exception as e:
        logger.error(f"Error fetching BetMGM positions: {e}")

    # Get FanDuel positions
    try:
        from tools.fanduel import fanduel_get_positions
        fd_positions = await fanduel_get_positions()
        all_positions.extend(fd_positions)
    except Exception as e:
        logger.error(f"Error fetching FanDuel positions: {e}")

    # Get PandaFX positions
    try:
        from tools.pandafx import pandafx_get_positions
        pf_positions = await pandafx_get_positions()
        all_positions.extend(pf_positions)
    except Exception as e:
        logger.error(f"Error fetching PandaFX positions: {e}")

    # Get ApexFutures positions
    try:
        from tools.apexfutures import apexfutures_get_positions
        af_positions = await apexfutures_get_positions()
        all_positions.extend(af_positions)
    except Exception as e:
        logger.error(f"Error fetching ApexFutures positions: {e}")

    total_value = sum(
        float(p.get("market_value", 0) or 0)
        for p in all_positions
    )

    return {
        "positions": all_positions,
        "total_value": round(total_value, 2),
        "timestamp": datetime.utcnow().isoformat(),
    }
