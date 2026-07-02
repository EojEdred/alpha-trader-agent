"""
Simulation Tools - Paper trading and execution simulation

Implements:
- simulate_order
- simulate_fill
- simulate_position
- simulate_pnl
- simulate_execution_plan
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from loguru import logger
import random


class SimulationEngine:
    """
    Paper trading and execution simulation engine.
    
    Provides realistic simulation of trading activities without real money.
    """
    
    def __init__(self, initial_capital: float = 10000.0, config: Dict = None):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.positions = {}  # symbol -> position details
        self.orders = {}     # order_id -> order details
        self.trades = []     # list of executed trades
        self.config = config or {}
        
        # Slippage and fee parameters
        self.base_slippage_pct = self.config.get('simulation', {}).get('base_slippage_pct', 0.001)  # 0.1%
        self.fee_per_share = self.config.get('simulation', {}).get('fee_per_share', 0.005)  # $0.005/share
        self.spread_multiplier = self.config.get('simulation', {}).get('spread_multiplier', 1.0)
        
        logger.info(f"Simulation engine initialized with ${initial_capital:,.2f}")
    
    async def simulate_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "limit",
        limit_price: float = None,
        stop_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Simulate placing an order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Number of shares/contracts
            order_type: 'market', 'limit', 'stop', etc.
            limit_price: Limit price for limit orders
            stop_price: Stop price for stop orders
            
        Returns:
            Order simulation result
        """
        logger.info(f"Simulating order: {side} {quantity} {symbol} ({order_type})")
        
        # Get current simulated price for the symbol
        current_price = await self._get_simulated_price(symbol)
        
        # For market orders, use current price
        if order_type.lower() == "market":
            execution_price = current_price
        else:
            execution_price = limit_price or current_price
        
        # Generate unique order ID
        order_id = f"SIMP_{uuid.uuid4().hex[:8].upper()}"
        
        # Calculate potential costs
        gross_amount = quantity * execution_price
        fees = quantity * self.fee_per_share
        net_amount = gross_amount + fees if side.lower() == "buy" else gross_amount - fees
        
        # Create order record
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'side': side.lower(),
            'quantity': quantity,
            'order_type': order_type.lower(),
            'limit_price': limit_price,
            'stop_price': stop_price,
            'execution_price': execution_price,
            'gross_amount': gross_amount,
            'fees': fees,
            'net_amount': net_amount,
            'status': 'submitted',
            'submitted_at': datetime.utcnow().isoformat(),
            'filled_at': None,
            'filled_quantity': 0,
            'average_fill_price': None
        }
        
        self.orders[order_id] = order
        
        result = {
            'order_id': order_id,
            'status': 'submitted',
            'symbol': symbol,
            'side': side.lower(),
            'quantity': quantity,
            'execution_price': execution_price,
            'gross_amount': gross_amount,
            'fees': fees,
            'net_amount': net_amount,
            'submitted_at': order['submitted_at']
        }
        
        logger.info(f"Order simulated: {order_id} - {side} {quantity} {symbol} @ ${execution_price:.2f}")
        return result
    
    async def execute_order(
        self,
        order_id: str,
        current_prices: Dict[str, float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute a simulated order based on current market conditions.
        
        Args:
            order_id: Order ID to execute
            current_prices: Current market prices (if not provided, will be simulated)
            
        Returns:
            Execution result
        """
        if order_id not in self.orders:
            raise ValueError(f"Order {order_id} not found in simulation")
        
        order = self.orders[order_id]
        
        if order['status'] in ['filled', 'cancelled', 'rejected']:
            return {
                'order_id': order_id,
                'status': order['status'],
                'message': f"Order already {order['status']}"
            }
        
        symbol = order['symbol']
        side = order['side']
        quantity = order['quantity']
        order_type = order['order_type']
        
        # Get current price for execution
        current_price = current_prices.get(symbol) if current_prices else await self._get_simulated_price(symbol)
        
        # Determine if order should execute based on type and prices
        should_execute = True
        
        if order_type == 'limit':
            limit_price = order['limit_price']
            if side == 'buy' and current_price > limit_price:
                should_execute = False
            elif side == 'sell' and current_price < limit_price:
                should_execute = False
        elif order_type == 'stop':
            stop_price = order['stop_price']
            if side == 'buy' and current_price < stop_price:
                should_execute = False  # Stop buy triggers when price rises above stop
            elif side == 'sell' and current_price > stop_price:
                should_execute = False  # Stop sell triggers when price falls below stop
        
        if not should_execute:
            return {
                'order_id': order_id,
                'status': 'pending',
                'message': f"Order condition not met (current: ${current_price:.2f})"
            }
        
        # Calculate execution price with slippage
        execution_price = await self._calculate_execution_price(
            current_price, 
            side, 
            quantity,
            order_type
        )
        
        # Update order status
        order['status'] = 'filled'
        order['filled_at'] = datetime.utcnow().isoformat()
        order['filled_quantity'] = quantity
        order['average_fill_price'] = execution_price
        
        # Update positions
        await self._update_positions(order)
        
        # Record the trade
        trade = {
            'trade_id': f"TRD_{uuid.uuid4().hex[:8].upper()}",
            'order_id': order_id,
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': execution_price,
            'fees': quantity * self.fee_per_share,
            'timestamp': order['filled_at']
        }
        self.trades.append(trade)
        
        # Update capital
        trade_value = quantity * execution_price
        if side == 'buy':
            self.current_capital -= (trade_value + trade['fees'])
        else:  # sell
            self.current_capital += (trade_value - trade['fees'])
        
        result = {
            'order_id': order_id,
            'status': 'filled',
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'execution_price': execution_price,
            'fees': trade['fees'],
            'net_amount': trade_value - trade['fees'] if side == 'sell' else -(trade_value + trade['fees']),
            'filled_at': order['filled_at'],
            'current_capital': self.current_capital
        }
        
        logger.info(f"Order filled: {order_id} - {side} {quantity} {symbol} @ ${execution_price:.2f}")
        return result
    
    async def _calculate_execution_price(
        self,
        current_price: float,
        side: str,
        quantity: int,
        order_type: str
    ) -> float:
        """
        Calculate execution price considering slippage and market impact.
        """
        # Base slippage
        slippage_factor = self.base_slippage_pct
        
        # Add market impact based on quantity (larger orders have more slippage)
        if quantity > 1000:
            slippage_factor *= (1 + (quantity - 1000) / 10000)  # Scale with size
        
        # Random component for realism
        random_factor = random.uniform(0.5, 1.5)
        total_slippage = slippage_factor * random_factor * self.spread_multiplier
        
        # Apply slippage in appropriate direction
        if side == 'buy':
            execution_price = current_price * (1 + total_slippage)
        else:  # sell
            execution_price = current_price * (1 - total_slippage)
        
        return round(execution_price, 2)
    
    async def _get_simulated_price(self, symbol: str) -> float:
        """
        Get a simulated price for a symbol based on historical patterns.
        """
        # For demo purposes, generate a reasonable price
        # In practice, this would come from a more sophisticated simulation model
        base_prices = {
            'SPY': 450.00,
            'QQQ': 350.00,
            'IWM': 150.00,
            'DIA': 350.00,
            'XAUUSD': 2000.00,
            'GC': 2000.00,
            'SI': 22.00,
            'ES': 4500.00,
            'NQ': 14000.00,
            'YM': 35000.00,
            'CL': 75.00,
            'EURUSD': 1.08,
            'GBPUSD': 1.27,
            'USDJPY': 149.00,
            'BTCUSDT': 40000.00,
            'ETHUSDT': 2500.00,
        }
        
        base_price = base_prices.get(symbol.upper(), random.uniform(50, 500))
        
        # Add some random movement
        movement = random.uniform(-0.02, 0.02)  # ±2% daily movement
        simulated_price = base_price * (1 + movement)
        
        return round(simulated_price, 2)
    
    async def _update_positions(self, order: Dict):
        """
        Update position records based on executed order.
        """
        symbol = order['symbol']
        side = order['side']
        quantity = order['filled_quantity']
        price = order['average_fill_price']
        
        if symbol not in self.positions:
            self.positions[symbol] = {
                'symbol': symbol,
                'quantity': 0,
                'avg_cost': 0.0,
                'market_value': 0.0,
                'unrealized_pnl': 0.0,
                'realized_pnl': 0.0
            }
        
        position = self.positions[symbol]
        
        if side == 'buy':
            # Calculate new average cost
            total_cost = (position['quantity'] * position['avg_cost']) + (quantity * price)
            total_qty = position['quantity'] + quantity
            new_avg_cost = total_cost / total_qty if total_qty > 0 else 0.0
            
            position['quantity'] += quantity
            position['avg_cost'] = new_avg_cost
        else:  # sell
            # Calculate realized P&L
            realized_pnl = quantity * (price - position['avg_cost'])
            position['realized_pnl'] += realized_pnl
            
            position['quantity'] -= quantity
            if position['quantity'] <= 0:
                # Clear position if fully sold
                position['avg_cost'] = 0.0
                position['quantity'] = 0
    
    async def get_simulated_positions(self) -> List[Dict]:
        """
        Get current simulated positions with updated market values.
        """
        positions_list = []
        
        for symbol, pos in self.positions.items():
            if pos['quantity'] != 0:
                # Get current simulated price
                current_price = await self._get_simulated_price(symbol)
                
                # Update market value and unrealized P&L
                market_value = pos['quantity'] * current_price
                unrealized_pnl = pos['quantity'] * (current_price - pos['avg_cost'])
                
                pos_copy = pos.copy()
                pos_copy['market_value'] = market_value
                pos_copy['unrealized_pnl'] = unrealized_pnl
                pos_copy['current_price'] = current_price
                
                positions_list.append(pos_copy)
        
        return positions_list
    
    async def get_simulation_status(self) -> Dict[str, Any]:
        """
        Get overall simulation status and metrics.
        """
        positions = await self.get_simulated_positions()
        
        total_unrealized_pnl = sum(p['unrealized_pnl'] for p in positions)
        total_realized_pnl = sum(p['realized_pnl'] for p in self.positions.values())
        total_pnl = total_unrealized_pnl + total_realized_pnl
        
        return {
            'current_capital': self.current_capital,
            'initial_capital': self.initial_capital,
            'total_pnl': total_pnl,
            'total_pnl_pct': (total_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0,
            'position_count': len([p for p in positions if p['quantity'] != 0]),
            'trade_count': len(self.trades),
            'positions': positions,
            'performance_metrics': {
                'win_rate': self._calculate_win_rate(),
                'avg_win': self._calculate_avg_win(),
                'avg_loss': self._calculate_avg_loss(),
                'profit_factor': self._calculate_profit_factor()
            }
        }
    
    def _calculate_win_rate(self) -> float:
        """Calculate win rate based on closed trades."""
        closed_trades = [t for t in self.trades if t.get('closed', False)]
        if not closed_trades:
            return 0.0
        
        winning_trades = [t for t in closed_trades if t.get('pnl', 0) > 0]
        return len(winning_trades) / len(closed_trades)
    
    def _calculate_avg_win(self) -> float:
        """Calculate average winning trade."""
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        if not winning_trades:
            return 0.0
        
        return sum(t.get('pnl', 0) for t in winning_trades) / len(winning_trades)
    
    def _calculate_avg_loss(self) -> float:
        """Calculate average losing trade."""
        losing_trades = [t for t in self.trades if t.get('pnl', 0) < 0]
        if not losing_trades:
            return 0.0
        
        return sum(t.get('pnl', 0) for t in losing_trades) / len(losing_trades)
    
    def _calculate_profit_factor(self) -> float:
        """Calculate profit factor (gains/losses)."""
        total_wins = sum(max(0, t.get('pnl', 0)) for t in self.trades)
        total_losses = abs(sum(min(0, t.get('pnl', 0)) for t in self.trades))
        
        return total_wins / total_losses if total_losses > 0 else float('inf')


async def simulate_execution_plan(
    execution_plan: Dict,
    simulation_engine: SimulationEngine,
    **kwargs
) -> Dict[str, Any]:
    """
    Simulate execution of a single execution plan.
    
    Args:
        execution_plan: ExecutionPlan object from router
        simulation_engine: Initialized SimulationEngine instance
        
    Returns:
        Simulation result
    """
    logger.info(f"Simulating execution plan: {execution_plan.get('intent_id')}")
    
    order_payload = execution_plan.get('order_payload', {})
    execution_mode = execution_plan.get('execution_mode', 'SIGNAL_ONLY')
    
    # If mode is SIGNAL_ONLY, just return without execution
    if execution_mode == 'SIGNAL_ONLY':
        result = {
            'plan_id': execution_plan.get('intent_id'),
            'execution_mode': execution_mode,
            'status': 'signal_only_processed',
            'message': 'Signal-only plan processed (no execution)'
        }
        logger.info(f"Signal-only plan processed: {execution_plan.get('intent_id')}")
        return result
    
    # For CONFIRM mode in simulation, treat as AUTO
    if execution_mode == 'CONFIRM':
        logger.info(f"Treating CONFIRM mode as AUTO in simulation: {execution_plan.get('intent_id')}")
    
    # Extract order details from payload
    symbol = order_payload.get('symbol', 'UNKNOWN')
    side = order_payload.get('side', 'buy')
    quantity = int(order_payload.get('quantity', order_payload.get('units', 1)))
    price = order_payload.get('price', order_payload.get('limit_price'))
    order_type = order_payload.get('orderType', 'limit')
    
    # Place simulated order
    order_result = await simulation_engine.simulate_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=price
    )
    
    # Immediately execute the order in simulation
    execution_result = await simulation_engine.execute_order(
        order_id=order_result['order_id']
    )
    
    result = {
        'plan_id': execution_plan.get('intent_id'),
        'execution_mode': execution_mode,
        'order_result': order_result,
        'execution_result': execution_result,
        'status': 'executed',
        'timestamp': datetime.utcnow().isoformat()
    }
    
    logger.info(f"Execution plan simulated: {execution_plan.get('intent_id')} - Status: {result['status']}")
    return result


async def run_simulation_workflow(
    execution_plans: List[Dict],
    initial_capital: float = 10000.0,
    config: Dict = None
) -> Dict[str, Any]:
    """
    Run a complete simulation workflow with multiple execution plans.
    
    Args:
        execution_plans: List of execution plans from router
        initial_capital: Starting capital for simulation
        config: Simulation configuration
        
    Returns:
        Complete simulation results
    """
    logger.info(f"Starting simulation workflow with {len(execution_plans)} execution plans")
    
    # Initialize simulation engine
    simulation_engine = SimulationEngine(initial_capital=initial_capital, config=config)
    
    # Execute each plan
    results = []
    for plan in execution_plans:
        try:
            result = await simulate_execution_plan(plan, simulation_engine)
            results.append(result)
        except Exception as e:
            logger.error(f"Error simulating plan {plan.get('intent_id')}: {e}")
            results.append({
                'plan_id': plan.get('intent_id'),
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            })
    
    # Get final simulation status
    final_status = await simulation_engine.get_simulation_status()
    
    simulation_results = {
        'workflow_id': f"SIM_{uuid.uuid4().hex[:8].upper()}",
        'initial_capital': initial_capital,
        'execution_plan_count': len(execution_plans),
        'successful_executions': len([r for r in results if r.get('status') != 'error']),
        'failed_executions': len([r for r in results if r.get('status') == 'error']),
        'results': results,
        'final_status': final_status,
        'completed_at': datetime.utcnow().isoformat()
    }
    
    logger.info(f"Simulation workflow completed: {simulation_results['workflow_id']}")
    logger.info(f"Final capital: ${final_status['current_capital']:,.2f}")
    logger.info(f"Total P&L: ${final_status['total_pnl']:+,.2f} ({final_status['total_pnl_pct']:+.2f}%)")
    
    return simulation_results