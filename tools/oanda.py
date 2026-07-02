"""
OANDA v20 API Adapter

For XAUUSD (gold) trading - AUTO execution mode.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

try:
    import oandapyV20
    from oandapyV20 import API
    from oandapyV20.endpoints import accounts, orders, positions, pricing, instruments
    OANDA_AVAILABLE = True
except ImportError:
    OANDA_AVAILABLE = False
    logger.warning("oandapyV20 not installed")


class OANDAClient:
    """OANDA v20 API client."""

    def __init__(self):
        self.api_key = os.getenv('OANDA_API_KEY')
        self.account_id = os.getenv('OANDA_ACCOUNT_ID')
        self.environment = os.getenv('OANDA_ENVIRONMENT', 'practice')  # 'practice' or 'live'

        if not OANDA_AVAILABLE:
            self.client = None
            return

        if self.api_key and self.account_id:
            self.client = API(
                access_token=self.api_key,
                environment=self.environment
            )
        else:
            self.client = None
            logger.warning("OANDA credentials not configured")

    async def get_account(self) -> Dict:
        """Get account details."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            r = accounts.AccountDetails(self.account_id)
            response = self.client.request(r)
            return response.get('account', {})
        except Exception as e:
            logger.error(f"OANDA account error: {e}")
            return {'error': str(e)}

    async def get_positions(self) -> List[Dict]:
        """Get open positions."""
        if not self.client:
            return []

        try:
            r = positions.OpenPositions(self.account_id)
            response = self.client.request(r)

            result = []
            for pos in response.get('positions', []):
                long_units = float(pos.get('long', {}).get('units', 0))
                short_units = float(pos.get('short', {}).get('units', 0))

                if long_units != 0:
                    result.append({
                        'venue': 'OANDA',
                        'symbol': pos['instrument'],
                        'side': 'long',
                        'size': long_units,
                        'entry': float(pos['long'].get('averagePrice', 0)),
                        'current': 0,  # Would need to fetch current price
                        'pnl': float(pos['long'].get('unrealizedPL', 0))
                    })

                if short_units != 0:
                    result.append({
                        'venue': 'OANDA',
                        'symbol': pos['instrument'],
                        'side': 'short',
                        'size': abs(short_units),
                        'entry': float(pos['short'].get('averagePrice', 0)),
                        'current': 0,
                        'pnl': float(pos['short'].get('unrealizedPL', 0))
                    })

            return result
        except Exception as e:
            logger.error(f"OANDA positions error: {e}")
            return []

    async def get_price(self, instrument: str = "XAU_USD") -> Dict:
        """Get current price."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            params = {"instruments": instrument}
            r = pricing.PricingInfo(self.account_id, params=params)
            response = self.client.request(r)

            prices = response.get('prices', [])
            if prices:
                return {
                    'instrument': instrument,
                    'bid': float(prices[0]['bids'][0]['price']),
                    'ask': float(prices[0]['asks'][0]['price']),
                    'time': prices[0]['time']
                }
            return {'error': 'No price data'}
        except Exception as e:
            logger.error(f"OANDA price error: {e}")
            return {'error': str(e)}

    async def place_order(
        self,
        instrument: str,
        units: int,
        side: str,
        order_type: str = "MARKET",
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None
    ) -> Dict:
        """
        Place an order.

        Args:
            instrument: e.g., "XAU_USD"
            units: Number of units (positive for buy, use side param)
            side: "buy" or "sell"
            order_type: "MARKET" or "LIMIT"
            price: Limit price (for LIMIT orders)
            stop_loss: Stop loss price
            take_profit: Take profit price
        """
        if not self.client:
            return {'error': 'Not connected', 'status': 'failed'}

        # Adjust units for direction
        if side == "sell":
            units = -abs(units)
        else:
            units = abs(units)

        logger.info(f"OANDA: Placing {side} order for {units} {instrument}")

        try:
            order_data = {
                "order": {
                    "instrument": instrument,
                    "units": str(units),
                    "type": order_type,
                    "positionFill": "DEFAULT"
                }
            }

            if order_type == "LIMIT" and price:
                order_data["order"]["price"] = str(price)

            if stop_loss:
                order_data["order"]["stopLossOnFill"] = {
                    "price": str(stop_loss)
                }

            if take_profit:
                order_data["order"]["takeProfitOnFill"] = {
                    "price": str(take_profit)
                }

            r = orders.OrderCreate(self.account_id, data=order_data)
            response = self.client.request(r)

            return {
                'status': 'filled' if 'orderFillTransaction' in response else 'pending',
                'order_id': response.get('orderFillTransaction', {}).get('id'),
                'fill_price': response.get('orderFillTransaction', {}).get('price'),
                'units': units,
                'instrument': instrument,
                'venue': 'OANDA',
                'executed_at': datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error(f"OANDA order error: {e}")
            return {'error': str(e), 'status': 'failed'}

    async def close_position(self, instrument: str = "XAU_USD") -> Dict:
        """Close all positions for an instrument."""
        if not self.client:
            return {'error': 'Not connected'}

        try:
            data = {"longUnits": "ALL", "shortUnits": "ALL"}
            r = positions.PositionClose(self.account_id, instrument, data)
            response = self.client.request(r)

            return {
                'status': 'closed',
                'instrument': instrument,
                'response': response
            }
        except Exception as e:
            logger.error(f"OANDA close error: {e}")
            return {'error': str(e)}


# Singleton instance
_oanda_client = None


def get_oanda_client() -> OANDAClient:
    global _oanda_client
    if _oanda_client is None:
        _oanda_client = OANDAClient()
    return _oanda_client


async def oanda_get_price(instrument: str = "XAU_USD") -> Dict:
    return await get_oanda_client().get_price(instrument)


async def oanda_place_order(**kwargs) -> Dict:
    return await get_oanda_client().place_order(**kwargs)


async def oanda_get_positions() -> List[Dict]:
    return await get_oanda_client().get_positions()


async def oanda_close_position(instrument: str = "XAU_USD") -> Dict:
    return await get_oanda_client().close_position(instrument)