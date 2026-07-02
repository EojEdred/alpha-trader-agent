"""
Strategy Tools - Trade ideation and risk management

Implements:
- generate_trade_idea
- calculate_position_size
- define_risk_params
- evaluate_portfolio_risk
- backtest_strategy
- select_best_trade
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger


async def generate_trade_idea(
    signals: Dict = None,
    risk_params: Dict = None,
    technical_signals: Dict = None,
    options_flow_signals: Dict = None,
    composite_sentiment: Dict = None,
    pattern_signals: Dict = None,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Generate trade recommendations from signals.

    In production, uses LLM for sophisticated trade ideation.
    """
    logger.info("Generating trade ideas")

    result = {
        'trade_recommendations': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    # Collect all signals
    all_signals = []
    if pattern_signals and 'patterns' in pattern_signals:
        all_signals = pattern_signals['patterns']
    if pattern_signals and 'signals' in pattern_signals:
        all_signals.extend(pattern_signals['signals'])

    # Simple rule-based trade generation (replace with LLM in production)
    convergence = pattern_signals.get('convergence_score', 0) if pattern_signals else 0

    if abs(convergence) > 0.5:
        direction = 'long' if convergence > 0 else 'short'
        conviction = min(abs(convergence), 1.0)

        # Get risk params from config
        risk_limits = config.risk_limits if config else None
        min_rr = risk_limits.min_risk_reward if risk_limits else 2.0

        trade = {
            'id': f"trade_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            'direction': direction,
            'conviction': round(conviction, 2),
            'entry_criteria': f"Signal convergence {convergence:.2f}",
            'risk_reward_target': min_rr,
            'signals_used': len(all_signals),
            'generated_at': datetime.utcnow().isoformat()
        }

        result['trade_recommendations'].append(trade)

    return result


def calculate_position_size(
    account_value: float,
    risk_per_trade_pct: float = 1.0,
    stop_distance: float = None,
    stop_distance_pct: float = None,
    entry_price: float = None,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate optimal position size based on risk parameters.

    Uses fixed fractional position sizing:
    Position Size = (Account * Risk%) / Stop Distance
    """
    logger.info(f"Calculating position size for ${account_value}")

    result = {
        'shares': 0,
        'dollar_value': 0.0,
        'risk_amount': 0.0,
        'position_pct': 0.0,
        'timestamp': datetime.utcnow().isoformat()
    }

    # Get risk limits
    if config and hasattr(config, 'risk_limits'):
        max_position_pct = config.risk_limits.max_position_pct
    else:
        max_position_pct = 5.0

    # Calculate risk amount
    risk_amount = account_value * (risk_per_trade_pct / 100)
    result['risk_amount'] = round(risk_amount, 2)

    # Calculate stop distance
    if stop_distance is None and stop_distance_pct and entry_price:
        stop_distance = entry_price * (stop_distance_pct / 100)

    if stop_distance and stop_distance > 0:
        # Position size based on risk
        shares = int(risk_amount / stop_distance)

        # Check against max position size
        if entry_price:
            dollar_value = shares * entry_price
            position_pct = (dollar_value / account_value) * 100

            # Cap at max position size
            if position_pct > max_position_pct:
                dollar_value = account_value * (max_position_pct / 100)
                shares = int(dollar_value / entry_price)
                position_pct = max_position_pct

            result['shares'] = shares
            result['dollar_value'] = round(dollar_value, 2)
            result['position_pct'] = round(position_pct, 2)

    return result


def define_risk_params(
    entry_price: float,
    direction: str = 'long',
    atr: float = None,
    support_level: float = None,
    resistance_level: float = None,
    risk_reward_ratio: float = 2.0,
    **kwargs
) -> Dict[str, Any]:
    """
    Define stop loss and take profit levels.
    """
    logger.info(f"Defining risk params for {direction} at {entry_price}")

    result = {
        'entry_price': entry_price,
        'direction': direction,
        'stop_loss': 0.0,
        'take_profit': 0.0,
        'risk_amount': 0.0,
        'reward_amount': 0.0,
        'risk_reward_ratio': 0.0,
        'timestamp': datetime.utcnow().isoformat()
    }

    # Default stop distance (2% if no ATR)
    stop_distance = atr if atr else entry_price * 0.02

    if direction == 'long':
        # Use support level if available, otherwise ATR-based
        if support_level and support_level < entry_price:
            result['stop_loss'] = support_level
        else:
            result['stop_loss'] = entry_price - stop_distance

        result['risk_amount'] = entry_price - result['stop_loss']
        result['reward_amount'] = result['risk_amount'] * risk_reward_ratio
        result['take_profit'] = entry_price + result['reward_amount']

    else:  # short
        if resistance_level and resistance_level > entry_price:
            result['stop_loss'] = resistance_level
        else:
            result['stop_loss'] = entry_price + stop_distance

        result['risk_amount'] = result['stop_loss'] - entry_price
        result['reward_amount'] = result['risk_amount'] * risk_reward_ratio
        result['take_profit'] = entry_price - result['reward_amount']

    result['risk_reward_ratio'] = risk_reward_ratio

    return result


async def check_pdt_compliance(**kwargs) -> bool:
    """
    Check if we are within PDT limits by querying Schwab's real transaction history.
    """
    from tools.schwab import get_schwab_client
    from datetime import datetime
    import json
    
    client = get_schwab_client()
    if not client.client:
        logger.warning("Schwab client not connected, skipping PDT real-time check")
        return False

    try:
        # Fetch trades from last 7 calendar days
        transactions = await client.get_transactions(days_back=7)
        
        # Group by symbol and date
        # We track opening and closing actions for each symbol per day
        # key: (symbol, date), value: {'opening': True/False, 'closing': True/False}
        daily_actions = {} 
        
        for tx in transactions:
            if tx.get('type') != 'TRADE':
                continue
                
            date = tx.get('tradeDate', tx.get('transactionDate', ''))[:10]
            if not date:
                continue
                
            for item in tx.get('transferItems', []):
                instr = item.get('instrument', {})
                if instr.get('assetType') == 'CURRENCY':
                    continue
                
                symbol = instr.get('symbol')
                effect = item.get('positionEffect') # "OPENING" or "CLOSING"
                
                if not symbol or not effect:
                    continue
                    
                key = (symbol, date)
                if key not in daily_actions:
                    daily_actions[key] = {'OPENING': False, 'CLOSING': False}
                
                daily_actions[key][effect] = True
        
        # A Day Trade is when a symbol has BOTH an OPENING and a CLOSING on the same day
        day_trade_count = 0
        for key, actions in daily_actions.items():
            if actions['OPENING'] and actions['CLOSING']:
                day_trade_count += 1
                logger.info(f"Day trade detected: {key[0]} on {key[1]}")
        
        logger.info(f"Schwab day trades in last 5 days: {day_trade_count}")
        # PDT guard disabled per user configuration — account does not use PDT limits.
        return True
        
    except Exception as e:
        logger.error(f"Error checking Schwab PDT compliance: {e}")
        return False


def evaluate_portfolio_risk(
    positions: List[Dict] = None,
    proposed_trade: Dict = None,
    current_portfolio: Dict = None,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluate portfolio-level risk metrics.
    """
    logger.info("Evaluating portfolio risk")

    positions = positions or []

    result = {
        'total_exposure': 0.0,
        'position_count': len(positions),
        'concentration_risk': {},
        'within_limits': True,
        'risk_approved': True,
        'warnings': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    # 1. Check PDT Guardrail
    if not check_pdt_compliance():
        result['risk_approved'] = False
        result['within_limits'] = False
        result['warnings'].append("PDT Limit Reached: 3 day trades in 5 days")

    # Get limits from config
    if config and hasattr(config, 'risk_limits'):
        max_positions = config.risk_limits.max_open_positions
        max_position_pct = config.risk_limits.max_position_pct
    else:
        max_positions = 10
        max_position_pct = 5.0

    # Check position count
    if len(positions) >= max_positions:
        result['within_limits'] = False
        result['risk_approved'] = False
        result['warnings'].append(f"Max positions ({max_positions}) reached")

    # Calculate total exposure
    for pos in positions:
        result['total_exposure'] += abs(pos.get('market_value', 0))

    # Check proposed trade
    if proposed_trade:
        trade_value = proposed_trade.get('dollar_value', 0)
        trade_pct = proposed_trade.get('position_pct', 0)

        if trade_pct > max_position_pct:
            result['risk_approved'] = False
            result['warnings'].append(f"Trade exceeds max position size ({max_position_pct}%)")

    return result


async def select_best_option_contract(symbol: str, direction: str, trade_type: str = "intraday") -> Optional[str]:
    """
    Select the best (ATM, liquid) option contract with expiration guardrails.
    """
    from tools.schwab import get_schwab_client
    client = get_schwab_client()
    
    chain = await client.get_option_chain(symbol)
    if 'error' in chain:
        return None
        
    try:
        put_call = "CALL" if direction == "long" else "PUT"
        exp_map = chain.get('callExpDateMap' if put_call == "CALL" else 'putExpDateMap', {})
        
        # 1. EXPIRATION GUARDRAIL
        # For swings, we need at least 3 days to expiry (DTE)
        # For scalps, we need at least 1 day to expiry (avoid 0DTE exercise risk)
        min_dte = 3 if trade_type == "swing" else 1
        
        valid_expirations = []
        for exp_key in exp_map.keys():
            # exp_key format is usually "2026-01-05:0" (date:days_to_expiry)
            try:
                days_to_expiry = int(exp_key.split(':')[-1])
                if days_to_expiry >= min_dte:
                    valid_expirations.append(exp_key)
            except:
                continue
        
        if not valid_expirations:
            logger.warning(f"No valid expirations found for {symbol} with min_dte {min_dte}")
            return None
            
        # Select the nearest valid expiration
        valid_expirations.sort(key=lambda x: int(x.split(':')[-1]))
        first_exp = exp_map[valid_expirations[0]]
        
        # 2. SELECTION (ATM)
        underlying_price = chain.get('underlyingPrice', 0)
        strikes = sorted(first_exp.keys(), key=lambda x: abs(float(x) - underlying_price))
        
        if not strikes:
            return None
            
        best_strike = first_exp[strikes[0]][0]
        selected_symbol = best_strike.get('symbol')
        
        logger.info(f"Selected {trade_type} {put_call} for {symbol}: {selected_symbol} ({valid_expirations[0].split(':')[1]} DTE)")
        return selected_symbol
        
    except Exception as e:
        logger.error(f"Error selecting option contract: {e}")
        return None


def select_best_trade(brain_decision: Dict, critique_result: Dict = None, **kwargs) -> Optional[Dict]:
    """
    Agent skill to filter and select the best setup for execution.
    Considers both initial inference and deep research critique.
    """
    if not brain_decision or brain_decision.get('direction') == 'none':
        return None
        
    symbol = brain_decision.get('symbol', '').upper()
    score = brain_decision.get('score', 0)
    trade_type = brain_decision.get('trade_type', 'intraday')
    
    # 0. Venue Authorization Check
    import os
    active_venues = os.getenv("ACTIVE_VENUES", "all").lower().split(",")
    
    # Map symbol to venue
    target_venue = "none"
    if any(x in symbol for x in ["SPY", "QQQ"]):
        target_venue = "schwab"
    elif any(x in symbol for x in ["NQ", "ES", "CL"]):
        target_venue = "topstep"
    elif any(x in symbol for x in ["XAU", "GOLD", "EUR", "GBP", "JPY", "AUD", "USD"]):
        target_venue = "oanda"
    
    if "all" not in active_venues and target_venue not in active_venues:
        logger.warning(f"🧠 Brain found trade for {symbol} but {target_venue} is not an authorized venue for this session.")
        return None

    # 1. Base Score Check (75+)
    if score < 75:
        logger.info(f"🧠 Brain trade rejected due to low score: {score}")
        return None

    # 2. Critique Check (Rating 7+)
    if critique_result:
        rating = critique_result.get('rating', 0)
        if rating < 7:
            logger.warning(f"🧠 Critique rejected setup with rating {rating}/10. Reason: {critique_result.get('critique')}")
            return None
        logger.info(f"🧠 Critique approved setup with rating {rating}/10")

    # 3. PDT/Swing logic
    from tools.strategy import check_pdt_compliance
    pdt_ok = kwargs.get('pdt_status', True)
    
    if not pdt_ok and trade_type == 'intraday':
        logger.warning(f"🧠 Brain wanted to SCALP {brain_decision.get('symbol')} but PDT is full. Trade blocked.")
        return None
    
    if not pdt_ok and trade_type == 'swing':
        logger.info(f"🧠 PDT is full, but Brain is initiating a SWING trade for {brain_decision.get('symbol')}. Proceeding...")
        return brain_decision

    logger.info(f"🧠 Brain selected {trade_type} trade: {brain_decision.get('symbol')} ({brain_decision.get('direction')}) - Score: {score}")
    return brain_decision


def strategy_filter(brain_decision: Any, critique_result: Any = None, **kwargs) -> Optional[Any]:
    """Wrapper for workflow orchestrator."""
    if isinstance(brain_decision, dict):
        return select_best_trade(brain_decision, critique_result, **kwargs)
    return None


async def backtest_strategy(
    strategy: Dict,
    historical_data: List[Dict],
    start_date: str = None,
    end_date: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Backtest a trading strategy on historical data.
    """
    logger.info("Running backtest")

    result = {
        'total_return': 0.0,
        'sharpe_ratio': 0.0,
        'max_drawdown': 0.0,
        'win_rate': 0.0,
        'trade_count': 0,
        'timestamp': datetime.utcnow().isoformat()
    }

    # Placeholder - implement full backtesting engine
    return result