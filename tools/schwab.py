"""
Charles Schwab API Adapter

For Equity and Options trading via schwab-py.
"""

import os
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

try:
    import schwab
    from schwab.client import Client
    from schwab.auth import client_from_token_file, client_from_manual_flow
    SCHWAB_AVAILABLE = True
except ImportError:
    SCHWAB_AVAILABLE = False
    logger.warning("schwab-py not installed")


class SchwabClient:
    """Charles Schwab API client."""

    def __init__(self):
        self.app_key = os.getenv('SCHWAB_APP_KEY')
        self.app_secret = os.getenv('SCHWAB_APP_SECRET')
        self.redirect_uri = os.getenv('SCHWAB_REDIRECT_URI')
        self.token_path = os.getenv('SCHWAB_TOKEN_PATH', 'schwab_token.json')
        
        self.client: Optional[Client] = None

        if not SCHWAB_AVAILABLE:
            return

        if self.app_key and self.app_secret and self.redirect_uri:
            try:
                # Try to load from token file first
                if os.path.exists(self.token_path):
                    self.client = client_from_token_file(
                        self.token_path, self.app_key, self.app_secret,
                        enforce_enums=False
                    )
                    logger.info("Schwab client initialized from token file")
                else:
                    logger.warning(f"Schwab token file not found at {self.token_path}. Call authenticate() to start manual flow.")
            except Exception as e:
                logger.error(f"Failed to initialize Schwab client: {e}")
        else:
            logger.warning("Schwab credentials not fully configured in environment")

    def authenticate(self):
        """Perform manual authentication flow."""
        if not SCHWAB_AVAILABLE:
            logger.error("schwab-py not installed")
            return
            
        if not (self.app_key and self.app_secret and self.redirect_uri):
            logger.error("Missing credentials for authentication")
            return

        try:
            self.client = client_from_manual_flow(
                self.app_key, 
                self.app_secret, 
                self.redirect_uri, 
                self.token_path
            )
            logger.info("Schwab authentication successful")
            return True
        except Exception as e:
            logger.error(f"Schwab authentication failed: {e}")
            return False

    async def get_account_numbers(self) -> List[str]:
        """Get account numbers (hashes)."""
        if not self.client:
            return []
        
        try:
            resp = self.client.get_account_numbers()
            if resp.status_code == 200:
                return [acc['hashValue'] for acc in resp.json()]
            return []
        except Exception as e:
            logger.error(f"Schwab account error: {e}")
            return []

    async def get_account(self, account_hash: str = None, fields: str = None) -> Dict:
        """Get account details including buying power and positions."""
        if not self.client:
            return {'error': 'Not connected'}
        
        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return {'error': 'No account found'}
                account_hash = hashes[0]
            
            if fields:
                resp = self.client.get_account(account_hash, fields=fields)
            else:
                resp = self.client.get_account(account_hash)
            
            if resp.status_code == 200:
                return resp.json()
            return {'error': f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"Schwab account error: {e}")
            return {'error': str(e)}

    async def get_positions(self, account_hash: str = None) -> List[Dict]:
        """Get open positions (equity + options)."""
        if not self.client:
            return []
        
        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return []
                account_hash = hashes[0]
            
            # Request positions field
            resp = self.client.get_account(account_hash, fields=self.client.Account.Fields.POSITIONS)
            if resp.status_code != 200:
                logger.warning(f"get_positions HTTP {resp.status_code}")
                return []
            
            data = resp.json()
            securities = data.get('securitiesAccount', {})
            positions_raw = securities.get('positions', [])
            
            positions = []
            for pos in positions_raw:
                instrument = pos.get('instrument', {})
                asset_type = instrument.get('assetType', '')
                
                base = {
                    'symbol': instrument.get('symbol', ''),
                    'asset_type': asset_type,
                    'quantity': pos.get('longQuantity', 0) - pos.get('shortQuantity', 0),
                    'market_value': pos.get('marketValue', 0),
                    'average_price': pos.get('averagePrice', 0),
                    'unrealized_pl': pos.get('currentDayProfitLoss', 0),
                }
                
                if asset_type == 'OPTION':
                    # Parse option symbol: e.g., "SPY   250620C00450000"
                    opt_sym = instrument.get('symbol', '')
                    underlying = instrument.get('underlyingSymbol', '')
                    option_type = instrument.get('putCall', '').lower()
                    strike = instrument.get('strikePrice', 0)
                    expiration = instrument.get('optionExpirationDate', '')
                    
                    # Calculate days to expiration
                    dte = None
                    try:
                        exp_dt = datetime.strptime(expiration, "%Y-%m-%d")
                        dte = (exp_dt - datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)).days
                    except Exception:
                        pass
                    
                    base.update({
                        'option_symbol': opt_sym,
                        'underlying': underlying,
                        'option_type': option_type,
                        'strike': strike,
                        'expiration': expiration,
                        'days_to_expiration': dte,
                    })
                
                positions.append(base)
            
            return positions
        except Exception as e:
            logger.error(f"Schwab get_positions error: {e}")
            return []

    async def get_order_status(self, order_id: str, account_hash: str = None) -> Dict:
        """Get status of a specific order."""
        if not self.client:
            return {'error': 'Not connected'}
        
        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return {'error': 'No account found'}
                account_hash = hashes[0]
            
            resp = self.client.get_order(order_id, account_hash)
            if resp.status_code == 200:
                return resp.json()
            return {'error': f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"Schwab order status error: {e}")
            return {'error': str(e)}

    async def get_price(self, symbol: str) -> Dict:
        """Get current quote for a symbol."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            resp = self.client.get_quote(symbol)
            if resp.status_code == 200:
                data = resp.json().get(symbol, {})
                quote = data.get('quote', {})
                return {
                    'symbol': symbol,
                    'bid': quote.get('bidPrice'),
                    'ask': quote.get('askPrice'),
                    'last': quote.get('lastPrice'),
                    'open': quote.get('openPrice'),
                    'high': quote.get('highPrice'),
                    'low': quote.get('lowPrice'),
                    'close': quote.get('closePrice'),
                    'volume': quote.get('totalVolume'),
                    'timestamp': datetime.utcnow().isoformat()
                }
            return {'error': f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"Schwab price error for {symbol}: {e}")
            return {'error': str(e)}

    async def get_transactions(self, account_hash: str = None, days_back: int = 7) -> List[Dict]:
        """Fetch transaction history to count day trades."""
        if not self.client:
            return []

        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return []
                account_hash = hashes[0]

            start_date = (datetime.utcnow() - timedelta(days=days_back))
            end_date = datetime.utcnow()

            resp = self.client.get_transactions(
                account_hash, 
                start_date=start_date, 
                end_date=end_date
            )
            
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception as e:
            logger.error(f"Schwab transactions error: {e}")
            return []

    async def get_option_chain(self, symbol: str, contract_type: str = None, strike_count: int = 10) -> Dict:
        """Fetch option chain for a symbol."""
        if not self.client:
            return {'error': 'Not connected'}
        
        try:
            kwargs = {'strike_count': strike_count, 'include_underlying_quote': True}
            if contract_type:
                kwargs['contract_type'] = contract_type.upper()
            
            resp = self.client.get_option_chain(symbol, **kwargs)
            if resp.status_code == 200:
                return resp.json()
            return {'error': f"HTTP {resp.status_code}"}
        except Exception as e:
            logger.error(f"Schwab option chain error for {symbol}: {e}")
            return {'error': str(e)}

    async def get_option_chain_parsed(
        self,
        symbol: str,
        direction: str = "long",
        expiration: str = None,
    ) -> Dict:
        """Fetch and parse option chain into brain-friendly format.

        Args:
            symbol: Underlying ticker
            direction: "long" for calls, "short" for puts
            expiration: Target expiration as "YYYY-MM-DD". If None, nearest expiration is used.

        Returns ATM +/- 2 strikes with Greeks for the chosen expiration.
        """
        chain = await self.get_option_chain(symbol)
        if 'error' in chain:
            return chain

        try:
            # Extract underlying price with multiple fallbacks
            underlying_price = 0.0
            if 'underlyingPrice' in chain:
                underlying_price = float(chain['underlyingPrice'])
            elif 'underlying' in chain and isinstance(chain['underlying'], dict):
                underlying_price = float(chain['underlying'].get('price', 0) or chain['underlying'].get('close', 0))
            elif 'underlyingPrice' in chain.get('underlying', {}):
                underlying_price = float(chain['underlying']['underlyingPrice'])

            if underlying_price <= 0:
                # Fallback: fetch from yfinance
                try:
                    import yfinance as yf
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="1d", interval="1m")
                    if not hist.empty:
                        underlying_price = float(hist["Close"].iloc[-1])
                        logger.info(f"Option chain: fetched underlying price from yfinance: {underlying_price}")
                except Exception as e:
                    logger.warning(f"Option chain: yfinance fallback failed: {e}")

            if underlying_price <= 0:
                return {'error': f'Could not determine underlying price for {symbol}'}

            exp_map = chain.get('callExpDateMap', {}) if direction == "long" else chain.get('putExpDateMap', {})
            if not exp_map:
                exp_map = chain.get('putExpDateMap', {}) if direction == "long" else chain.get('callExpDateMap', {})

            if not exp_map:
                return {'error': 'No option chain data'}

            # Select expiration
            available = sorted(exp_map.keys())
            if expiration:
                # Find first available expiration >= target date
                chosen = None
                for exp_key in available:
                    exp_date = exp_key.split(':')[0]
                    if exp_date >= expiration:
                        chosen = exp_key
                        break
                if not chosen:
                    chosen = available[-1]  # fall back to furthest out
                logger.info(f"Option chain: using expiration {chosen} for {symbol} (target {expiration})")
            else:
                chosen = available[0]  # nearest

            strikes = exp_map[chosen]
            
            # Find ATM strike
            atm_diff = float('inf')
            atm_strike = None
            for strike_str, strike_data in strikes.items():
                strike = float(strike_str)
                diff = abs(strike - underlying_price)
                if diff < atm_diff:
                    atm_diff = diff
                    atm_strike = strike
            
            # Collect ATM and nearest strikes
            selected = []
            for strike_str, strike_data in strikes.items():
                strike = float(strike_str)
                if abs(strike - atm_strike) <= (underlying_price * 0.03):  # Within 3%
                    option = strike_data[0] if strike_data else {}
                    selected.append({
                        'strike': strike,
                        'bid': option.get('bid', 0),
                        'ask': option.get('ask', 0),
                        'last': option.get('last', 0),
                        'volume': option.get('totalVolume', 0),
                        'open_interest': option.get('openInterest', 0),
                        'delta': option.get('delta', 0),
                        'gamma': option.get('gamma', 0),
                        'theta': option.get('theta', 0),
                        'vega': option.get('vega', 0),
                        'implied_volatility': option.get('volatility', 0),
                        'dte': option.get('daysToExpiration', 0),
                    })
            
            selected.sort(key=lambda x: x['strike'])
            
            return {
                'underlying': symbol,
                'underlying_price': underlying_price,
                'expiration': chosen.split(':')[0],
                'option_type': 'call' if 'callExpDateMap' in chain and exp_map == chain['callExpDateMap'] else 'put',
                'strikes': selected,
            }
        except Exception as e:
            logger.error(f"Option chain parse error: {e}")
            return {'error': str(e)}

    async def place_option_order(
        self,
        symbol: str,
        quantity: int,
        side: str, # "buy_to_open", "sell_to_close"
        account_hash: str = None,
        order_type: str = "LIMIT",
        price: float = None
    ) -> Dict:
        """Place an option order. Supports partial closes via quantity."""
        logger.info(f"Schwab place_option_order: {side} {quantity}x {symbol} @ {price} ({order_type})")
        
        if not self.client:
            logger.error("Schwab place_option_order: Not connected")
            return {'error': 'Not connected', 'status': 'failed'}

        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    logger.error("Schwab place_option_order: No account found")
                    return {'error': 'No account found', 'status': 'failed'}
                account_hash = hashes[0]

            from schwab.orders.options import (
                option_buy_to_open_market, option_buy_to_open_limit,
                option_sell_to_close_market, option_sell_to_close_limit
            )
            from schwab.orders.common import Duration, Session

            if side == "buy_to_open":
                if order_type.upper() == "MARKET":
                    builder = option_buy_to_open_market(symbol, quantity)
                else:
                    if price is None:
                        logger.error("Schwab place_option_order: Limit price required for LIMIT order")
                        return {'error': 'Limit price required for LIMIT order', 'status': 'failed'}
                    builder = option_buy_to_open_limit(symbol, quantity, price)
            elif side == "sell_to_close":
                if order_type.upper() == "MARKET":
                    builder = option_sell_to_close_market(symbol, quantity)
                else:
                    if price is None:
                        logger.error("Schwab place_option_order: Limit price required for LIMIT order")
                        return {'error': 'Limit price required for LIMIT order', 'status': 'failed'}
                    builder = option_sell_to_close_limit(symbol, quantity, price)
            else:
                logger.error(f"Schwab place_option_order: Unsupported side {side}")
                return {'error': f"Unsupported option side: {side}", 'status': 'failed'}

            builder.set_duration(Duration.DAY)
            builder.set_session(Session.NORMAL)

            order_build = builder.build()
            logger.info(f"Schwab place_option_order: Built order for account {account_hash[:8]}... — submitting")
            
            resp = self.client.place_order(account_hash, order_build)
            
            if resp.status_code in [200, 201]:
                order_id = resp.headers.get('Location', '').split('/')[-1]
                logger.info(f"Schwab place_option_order: SUCCESS — order_id={order_id}")
                return {
                    'status': 'submitted',
                    'order_id': order_id,
                    'symbol': symbol,
                    'quantity': quantity,
                    'side': side,
                    'order_type': order_type,
                    'price': price,
                    'venue': 'Schwab',
                    'executed_at': datetime.utcnow().isoformat()
                }
            
            logger.error(f"Schwab place_option_order: FAILED — HTTP {resp.status_code}: {resp.text[:200]}")
            return {'error': f"HTTP {resp.status_code}: {resp.text}", 'status': 'failed'}

        except Exception as e:
            logger.error(f"Schwab option order error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def place_credit_spread(
        self,
        underlying: str,
        short_strike: float,
        long_strike: float,
        expiration_date,  # datetime.date
        quantity: int,
        net_credit: float,
        spread_type: str = "PUT",  # PUT for bull put vertical (put credit spread)
        account_hash: str = None,
    ) -> Dict:
        """Place an option credit spread (vertical)."""
        logger.info(
            f"Schwab place_credit_spread: {underlying} {spread_type} "
            f"{short_strike}/{long_strike} x{quantity} @ ${net_credit} credit"
        )
        
        if not self.client:
            return {'error': 'Not connected', 'status': 'failed'}
        
        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return {'error': 'No account found', 'status': 'failed'}
                account_hash = hashes[0]
            
            # Build option symbols
            exp_str = expiration_date.strftime("%y%m%d")
            opt_letter = "P" if spread_type.upper() == "PUT" else "C"
            short_sym = f"{underlying:<6}{exp_str}{opt_letter}{int(short_strike * 1000):08d}"
            long_sym = f"{underlying:<6}{exp_str}{opt_letter}{int(long_strike * 1000):08d}"
            
            from schwab.orders.options import bull_put_vertical_open, bull_call_vertical_open
            from schwab.orders.common import Duration, Session
            
            if spread_type.upper() == "PUT":
                # Put credit spread: sell higher strike, buy lower strike
                builder = bull_put_vertical_open(long_sym, short_sym, quantity, net_credit)
            else:
                # Call credit spread: sell lower strike, buy higher strike
                builder = bull_call_vertical_open(long_sym, short_sym, quantity, net_credit)
            
            builder.set_duration(Duration.DAY)
            builder.set_session(Session.NORMAL)
            
            order_build = builder.build()
            logger.info(f"Schwab place_credit_spread: submitting {short_strike}/{long_strike}")
            
            resp = self.client.place_order(account_hash, order_build)
            
            if resp.status_code in [200, 201]:
                order_id = resp.headers.get('Location', '').split('/')[-1]
                logger.info(f"Schwab place_credit_spread: SUCCESS — order_id={order_id}")
                return {
                    'status': 'submitted',
                    'order_id': order_id,
                    'underlying': underlying,
                    'short_strike': short_strike,
                    'long_strike': long_strike,
                    'quantity': quantity,
                    'net_credit': net_credit,
                    'spread_type': spread_type,
                    'venue': 'Schwab',
                    'executed_at': datetime.utcnow().isoformat()
                }
            
            logger.error(f"Schwab place_credit_spread: FAILED — HTTP {resp.status_code}: {resp.text[:200]}")
            return {'error': f"HTTP {resp.status_code}: {resp.text}", 'status': 'failed'}
        
        except Exception as e:
            logger.error(f"Schwab credit spread error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        account_hash: str = None,
        order_type: str = "MARKET",
        price: float = None
    ) -> Dict:
        """Place an equity order."""
        if not self.client:
            return {'error': 'Not connected', 'status': 'failed'}

        try:
            if not account_hash:
                hashes = await self.get_account_numbers()
                if not hashes:
                    return {'error': 'No account found', 'status': 'failed'}
                account_hash = hashes[0]

            from schwab.orders.common import Duration, Session
            from schwab.orders.equities import (
                equity_buy_market, equity_sell_market,
                equity_buy_limit, equity_sell_limit
            )

            if side.lower() == 'buy':
                if order_type.upper() == "MARKET":
                    builder = equity_buy_market(symbol, quantity)
                else:
                    builder = equity_buy_limit(symbol, quantity, price)
            else:
                if order_type.upper() == "MARKET":
                    builder = equity_sell_market(symbol, quantity)
                else:
                    builder = equity_sell_limit(symbol, quantity, price)

            builder.set_duration(Duration.DAY)
            builder.set_session(Session.NORMAL)

            resp = self.client.place_order(account_hash, builder.build())
            
            if resp.status_code in [200, 201]:
                order_id = resp.headers.get('Location', '').split('/')[-1]
                return {
                    'status': 'submitted',
                    'order_id': order_id,
                    'symbol': symbol,
                    'quantity': quantity,
                    'venue': 'Schwab',
                    'executed_at': datetime.utcnow().isoformat()
                }
            else:
                return {'error': f"HTTP {resp.status_code}: {resp.text}", 'status': 'failed'}

        except Exception as e:
            logger.error(f"Schwab order error: {e}")
            return {'error': str(e), 'status': 'failed'}


# Singleton instance
_schwab_client = None

def get_schwab_client() -> SchwabClient:
    global _schwab_client
    if _schwab_client is None:
        _schwab_client = SchwabClient()
    return _schwab_client

async def schwab_get_price(symbol: str, **kwargs) -> Dict:
    return await get_schwab_client().get_price(symbol)

async def schwab_place_order(**kwargs) -> Dict:
    return await get_schwab_client().place_order(**kwargs)

async def schwab_get_positions(**kwargs) -> List[Dict]:
    return await get_schwab_client().get_positions()

async def schwab_get_account(**kwargs) -> Dict:
    return await get_schwab_client().get_account()

async def schwab_place_credit_spread(**kwargs) -> Dict:
    return await get_schwab_client().place_credit_spread(**kwargs)


async def schwab_place_option_order(**kwargs) -> Dict:
    # ─── PAPER TRADE MODE ───
    import yaml
    try:
        with open("/Users/macbook/Desktop/allternit-workspace/allternit-alpha-trader-agent/config/trading_params.yaml") as f:
            cfg = yaml.safe_load(f)
        if cfg.get("PAPER_TRADE", True):
            symbol = kwargs.get('symbol', 'unknown')
            side = kwargs.get('side', 'unknown')
            quantity = kwargs.get('quantity', 0)
            price = kwargs.get('price', 0)
            logger.info(f"📝 PAPER TRADE: Would place {side} {quantity}x {symbol} @ ${price}")
            return {"status": "submitted", "paper_trade": True, "symbol": symbol, "side": side, "quantity": quantity, "price": price}
    except Exception:
        pass
    
    result = await get_schwab_client().place_option_order(**kwargs)
    
    # Log trade to audit DB
    try:
        from tools.reporting_fixed import log_trade
        side = kwargs.get('side', 'unknown')
        symbol = kwargs.get('symbol', 'unknown')
        quantity = kwargs.get('quantity', 0)
        price = kwargs.get('price', 0)
        order_type = kwargs.get('order_type', 'MARKET')
        order_id = result.get('order_id') if isinstance(result, dict) else None
        status = 'submitted' if isinstance(result, dict) and result.get('status') == 'submitted' else 'failed'
        
        log_trade(
            venue='schwab',
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            order_id=order_id,
            status=status,
            notes=f"Option order {side}",
            details=result if isinstance(result, dict) else {'error': str(result)}
        )
    except Exception as e:
        logger.debug(f"Trade logging failed: {e}")
    
    return result

async def schwab_get_option_chain_parsed(
    symbol: str,
    direction: str = "long",
    expiration: str = None,
    **kwargs,
) -> Dict:
    return await get_schwab_client().get_option_chain_parsed(symbol, direction, expiration=expiration)

async def schwab_get_order_status(order_id: str = None, exit_results: Any = None, **kwargs) -> Dict:
    """Fetch status for a single order_id or extract it from exit_results."""
    if order_id is None and exit_results is not None:
        # Try to pull the order id from the exit result(s)
        if isinstance(exit_results, dict):
            order_id = exit_results.get("order_id") or exit_results.get("schwab_order_id")
        elif isinstance(exit_results, list) and exit_results:
            order_id = exit_results[0].get("order_id") if isinstance(exit_results[0], dict) else None
    if not order_id:
        return {"status": "skipped", "reason": "No order_id provided"}
    return await get_schwab_client().get_order_status(order_id)


async def schwab_check_compliance(**kwargs) -> Dict:
    """Check Schwab account compliance: buying power, day trade count."""
    client = get_schwab_client()
    if not client.client:
        return {"can_trade": False, "reason": "Schwab not connected"}
    
    try:
        account = await client.get_account()
        if 'error' in account:
            return {"can_trade": False, "reason": account['error']}
        
        securities = account.get('securitiesAccount', {})
        
        # Buying power check
        projected = securities.get('projectedBalances', {})
        buying_power = projected.get('buyingPower', 0) or projected.get('availableFunds', 0)
        if buying_power < 500:
            return {"can_trade": False, "reason": f"Insufficient buying power: ${buying_power}", "buying_power": buying_power}
        
        # Day trade count (approximate from transactions)
        # NOTE: User requested PDT override — account has $2K+ and claims no PDT limit
        transactions = await client.get_transactions(days_back=5)
        day_trades = 0
        trade_dates = {}
        for tx in transactions:
            if tx.get('type') in ('TRADE', 'BUY_TO_OPEN', 'SELL_TO_CLOSE'):
                tx_date = tx.get('tradeDate', tx.get('date', ''))[:10]
                sym = tx.get('transactionItem', {}).get('instrument', {}).get('symbol', '')
                if tx_date and sym:
                    key = f"{tx_date}:{sym}"
                    if key not in trade_dates:
                        trade_dates[key] = []
                    trade_dates[key].append(tx.get('type'))
        
        # Count same-day buy+sell as day trade
        for key, types in trade_dates.items():
            has_buy = any('BUY' in t or 'BUY_TO_OPEN' in t for t in types)
            has_sell = any('SELL' in t or 'SELL_TO_CLOSE' in t for t in types)
            if has_buy and has_sell:
                day_trades += 1
        
        # PDT disabled per user request — account has $2K+ equity
        can_trade = True
        
        return {
            "can_trade": True,
            "buying_power": buying_power,
            "day_trades_5d": day_trades,
            "account_value": securities.get('currentBalances', {}).get('liquidationValue', 0),
            "reason": f"BP: ${buying_power}, Day trades: {day_trades} (PDT override active)"
        }
    except Exception as e:
        logger.error(f"Schwab compliance check error: {e}")
        return {"can_trade": False, "reason": str(e)}


def check_schwab_token_health() -> Dict[str, Any]:
    """
    Check Schwab token freshness and warn before expiry.

    Schwab refresh tokens expire after 7 days. This function reads the saved
    token file and reports how much time is left, alerting when within 24h.
    """
    token_path = os.getenv('SCHWAB_TOKEN_PATH', 'schwab_token.json')
    now = datetime.utcnow()
    result = {
        "healthy": False,
        "token_path": token_path,
        "access_token_expires_at": None,
        "refresh_token_expires_at": None,
        "access_token_minutes_left": 0,
        "refresh_token_hours_left": 0,
        "alert": None,
    }

    if not os.path.exists(token_path):
        result["alert"] = "Schwab token file missing — reauth required"
        logger.warning(result["alert"])
        return result

    try:
        with open(token_path, 'r') as f:
            token = json.load(f)
    except Exception as e:
        result["alert"] = f"Failed to read Schwab token: {e}"
        logger.error(result["alert"])
        return result

    # schwab-py stores token as {creation_timestamp, token: {...}}
    nested = token.get('token', {}) if isinstance(token.get('token'), dict) else token

    # Access token expiry (use UTC consistently)
    access_expires = nested.get('expires_at') or token.get('expires_at')
    access_expires_in = nested.get('expires_in') or token.get('expires_in', 1800)
    if access_expires:
        try:
            access_dt = datetime.utcfromtimestamp(access_expires)
            result["access_token_expires_at"] = access_dt.isoformat()
            result["access_token_minutes_left"] = int((access_dt - now).total_seconds() / 60)
        except Exception:
            pass

    # Refresh token expiry: Schwab refresh tokens last 7 days from creation.
    # The API does not always return refresh_token_expires_in, so fall back to
    # creation_timestamp + 7 days.
    refresh_expires_in = nested.get('refresh_token_expires_in') or token.get('refresh_token_expires_in')
    creation_ts = token.get('creation_timestamp')
    if refresh_expires_in and creation_ts:
        try:
            refresh_dt = datetime.utcfromtimestamp(creation_ts + refresh_expires_in)
            result["refresh_token_expires_at"] = refresh_dt.isoformat()
            result["refresh_token_hours_left"] = int((refresh_dt - now).total_seconds() / 3600)
        except Exception:
            pass
    elif creation_ts:
        # Schwab refresh tokens expire 7 days after creation
        try:
            refresh_dt = datetime.utcfromtimestamp(creation_ts + 7 * 24 * 3600)
            result["refresh_token_expires_at"] = refresh_dt.isoformat()
            result["refresh_token_hours_left"] = int((refresh_dt - now).total_seconds() / 3600)
        except Exception:
            pass

    # Health assessment
    access_ok = result["access_token_minutes_left"] > 10
    refresh_ok = result["refresh_token_hours_left"] > 24
    result["healthy"] = access_ok and refresh_ok

    if not access_ok:
        result["alert"] = (
            f"Schwab access token expires in {result['access_token_minutes_left']} minutes. "
            "The client will try to refresh automatically."
        )
        logger.warning(result["alert"])
    elif not refresh_ok:
        result["alert"] = (
            f"Schwab refresh token expires in {result['refresh_token_hours_left']} hours. "
            "Run reauth_schwab.py before it expires to avoid manual reauth during trading."
        )
        logger.warning(result["alert"])
        # Telegram alert for refresh-token expiry
        try:
            from tools.delivery import send_telegram
            send_telegram(message=f"⚠️ Schwab refresh token expires in {result['refresh_token_hours_left']}h. Reauth needed.")
        except Exception:
            pass
    else:
        logger.info(
            f"Schwab token healthy: access expires in {result['access_token_minutes_left']}m, "
            f"refresh expires in {result['refresh_token_hours_left']}h"
        )

    return result
