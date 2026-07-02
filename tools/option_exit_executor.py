"""
Option Exit Executor

Takes exit decisions from the profit-locking engine and executes them
via schwab_place_option_order. Handles multiple partial exits.
"""

from typing import Dict, List
from loguru import logger


async def execute_option_exits(exit_decisions: dict = None, **kwargs) -> dict:
    """
    Execute option exit actions from the profit-locking engine.
    
    Args:
        exit_decisions: Dict with 'actions' list from evaluate_profit_locking
        
    Returns:
        Dict with exit_results list
    """
    from tools.schwab import schwab_place_option_order
    from tools.reporting_fixed import log_trade
    
    if not exit_decisions:
        return {"status": "no_decisions", "exit_results": []}
    
    actions = exit_decisions.get("actions", [])
    if not actions:
        return {"status": "no_actions", "exit_results": []}
    
    results = []
    
    for action in actions:
        contracts_to_close = action.get("contracts_to_close", 0)
        if contracts_to_close <= 0:
            # Tier 4 trail activation — no order to place
            results.append({
                "symbol": action.get("symbol"),
                "action": action.get("action"),
                "status": "trail_activated",
                "reason": action.get("reason"),
            })
            continue
        
        symbol = action.get("symbol", "")
        order_type = action.get("order_type", "MARKET")
        limit_price = action.get("limit_price")
        
        try:
            result = await schwab_place_option_order(
                symbol=symbol,
                quantity=contracts_to_close,
                side="sell_to_close",
                order_type=order_type,
                price=limit_price,
            )
            
            results.append({
                "symbol": symbol,
                "action": action.get("action"),
                "contracts": contracts_to_close,
                "order_type": order_type,
                "price": limit_price,
                "status": result.get("status", "unknown"),
                "order_id": result.get("order_id"),
                "reason": action.get("reason"),
            })
            
            logger.info(f"✅ Exit executed: {action.get('action')} {contracts_to_close}x {symbol}")
            
        except Exception as e:
            logger.error(f"❌ Exit failed for {symbol}: {e}")
            results.append({
                "symbol": symbol,
                "action": action.get("action"),
                "contracts": contracts_to_close,
                "status": "failed",
                "error": str(e),
                "reason": action.get("reason"),
            })
    
    return {
        "status": "executed",
        "exit_results": results,
        "count": len(results),
    }
