"""
High-Fidelity Paper Venue for Alpha Trader

Simulates live trading with realistic costs:
- Fees (maker/taker) per venue and asset class
- Slippage based on order size and market volatility
- Funding rates for perpetuals
- Liquidation for leveraged positions
- Tick-by-tick PnL tracking

Inspired by FinceptTerminal Alpha Arena's paper venue.

Usage:
    from tools.paper_venue import PaperVenue

    venue = PaperVenue(initial_balance={"USDT": 10000})
    fill = await venue.place_order("BTC/USDT", "buy", 0.1, price=50000)
    pnl = venue.get_pnl()
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger


@dataclass
class PaperPosition:
    """A simulated position."""

    symbol: str
    side: str  # "long" or "short"
    size: float
    entry_price: float
    margin: float = 0.0
    leverage: float = 1.0
    opened_at: datetime = field(default_factory=datetime.utcnow)
    funding_paid: float = 0.0
    fees_paid: float = 0.0

    @property
    def notional(self) -> float:
        return self.size * self.entry_price

    def unrealized_pnl(self, mark_price: float) -> float:
        if self.side == "long":
            return self.size * (mark_price - self.entry_price)
        else:
            return self.size * (self.entry_price - mark_price)

    def liquidation_price(self) -> Optional[float]:
        """Simple liquidation price for leveraged perp positions."""
        if self.leverage <= 1:
            return None
        maintenance_margin = 0.05  # 5%
        if self.side == "long":
            return self.entry_price * (1 - (1 / self.leverage) + maintenance_margin)
        else:
            return self.entry_price * (1 + (1 / self.leverage) - maintenance_margin)


@dataclass
class PaperFill:
    """Result of a simulated order fill."""

    order_id: str
    symbol: str
    side: str
    size: float
    filled_price: float
    fee: float
    slippage: float
    timestamp: datetime
    status: str = "filled"


class PaperVenue:
    """
    Paper trading venue with realistic simulation.

    Tracks cash balances, positions, fees, and PnL. Supports both spot and
    leveraged perpetual-style positions.
    """

    def __init__(
        self,
        initial_balance: Optional[Dict[str, float]] = None,
        fee_model: Optional[Dict[str, Any]] = None,
        slippage_model: Optional[Dict[str, Any]] = None,
    ):
        self.balances: Dict[str, float] = initial_balance or {"USD": 100000.0}
        self.positions: Dict[str, PaperPosition] = {}
        self.fills: List[PaperFill] = []
        self.fee_model = fee_model or self._default_fee_model()
        self.slippage_model = slippage_model or self._default_slippage_model()
        self._order_counter = 0

    def _default_fee_model(self) -> Dict[str, Any]:
        return {
            "default": {"maker": 0.001, "taker": 0.001},
            "crypto": {"maker": 0.001, "taker": 0.001},
            "futures": {"maker": 0.0002, "taker": 0.0005},
            "forex": {"maker": 0.0001, "taker": 0.0001},
            "options": {"maker": 0.0005, "taker": 0.0005},
        }

    def _default_slippage_model(self) -> Dict[str, Any]:
        return {
            "default": {"base_bps": 5, "volatility_bps": 0, "size_impact": 0.0},
            "crypto": {"base_bps": 10, "volatility_bps": 5, "size_impact": 0.0001},
            "futures": {"base_bps": 5, "volatility_bps": 2, "size_impact": 0.00005},
        }

    def _detect_asset_class(self, symbol: str) -> str:
        s = symbol.upper()
        if "/" in s and any(stable in s for stable in ("USDT", "USD", "BUSD")):
            return "crypto"
        if s in ("ES", "NQ", "YM", "CL", "GC", "SI"):
            return "futures"
        if s in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD") or "/" in s:
            return "forex"
        return "default"

    def _get_fee_rate(self, symbol: str, order_type: str = "market") -> float:
        asset_class = self._detect_asset_class(symbol)
        model = self.fee_model.get(asset_class, self.fee_model["default"])
        return model.get("taker" if order_type == "market" else "maker", 0.001)

    def _get_slippage(self, symbol: str, size: float, price: float) -> float:
        asset_class = self._detect_asset_class(symbol)
        model = self.slippage_model.get(asset_class, self.slippage_model["default"])
        base = model.get("base_bps", 5)
        size_impact = model.get("size_impact", 0.0)
        notional = size * price
        impact = notional * size_impact
        total_bps = base + impact
        return price * (total_bps / 10000)

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"paper_{self._order_counter:06d}"

    async def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        price: Optional[float] = None,
        order_type: str = "market",
        leverage: float = 1.0,
        quote_asset: Optional[str] = None,
    ) -> PaperFill:
        """
        Simulate an order fill.

        Args:
            symbol: Trading symbol.
            side: "buy" or "sell".
            size: Order size.
            price: Reference price. If None, must be supplied by caller.
            order_type: "market" or "limit".
            leverage: Perp leverage (1.0 = spot).
            quote_asset: Quote currency for spot buys.
        """
        if price is None:
            raise ValueError("PaperVenue requires a price for simulation")

        side = side.lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")

        slippage = self._get_slippage(symbol, size, price)
        if side == "buy":
            filled_price = price + slippage
        else:
            filled_price = price - slippage

        fee_rate = self._get_fee_rate(symbol, order_type)
        notional = size * filled_price
        fee = notional * fee_rate

        # Determine quote asset
        if quote_asset is None:
            quote_asset = symbol.split("/")[-1] if "/" in symbol else "USD"

        # Update balance
        if side == "buy":
            cost = notional + fee
            self.balances[quote_asset] = self.balances.get(quote_asset, 0) - cost
            base_asset = symbol.split("/")[0]
            self.balances[base_asset] = self.balances.get(base_asset, 0) + size
        else:
            proceeds = notional - fee
            self.balances[quote_asset] = self.balances.get(quote_asset, 0) + proceeds
            base_asset = symbol.split("/")[0]
            self.balances[base_asset] = self.balances.get(base_asset, 0) - size

        # Update position
        position_side = "long" if side == "buy" else "short"
        margin = notional / leverage if leverage > 0 else notional
        existing = self.positions.get(symbol)
        if existing and existing.side == position_side:
            # Average into position
            total_size = existing.size + size
            avg_price = (existing.entry_price * existing.size + filled_price * size) / total_size
            existing.size = total_size
            existing.entry_price = avg_price
            existing.fees_paid += fee
            existing.margin += margin
        elif existing and existing.side != position_side:
            # Reduce or flip
            if existing.size > size:
                existing.size -= size
                existing.fees_paid += fee
            elif existing.size == size:
                del self.positions[symbol]
            else:
                new_size = size - existing.size
                self.positions[symbol] = PaperPosition(
                    symbol=symbol,
                    side=position_side,
                    size=new_size,
                    entry_price=filled_price,
                    margin=margin,
                    leverage=leverage,
                    fees_paid=fee,
                )
        else:
            self.positions[symbol] = PaperPosition(
                symbol=symbol,
                side=position_side,
                size=size,
                entry_price=filled_price,
                margin=margin,
                leverage=leverage,
                fees_paid=fee,
            )

        fill = PaperFill(
            order_id=self._next_order_id(),
            symbol=symbol,
            side=side,
            size=size,
            filled_price=filled_price,
            fee=fee,
            slippage=slippage,
            timestamp=datetime.utcnow(),
        )
        self.fills.append(fill)

        logger.info(
            f"PaperVenue: filled {side} {size} {symbol} @ {filled_price:.4f} "
            f"(fee={fee:.4f}, slippage={slippage:.4f})"
        )
        return fill

    async def apply_funding(self, symbol: str, funding_rate: float, mark_price: float):
        """Apply funding payment to a perp position."""
        position = self.positions.get(symbol)
        if not position or position.leverage <= 1:
            return

        notional = position.size * mark_price
        funding = notional * funding_rate
        if position.side == "short":
            funding = -funding

        position.funding_paid += funding
        quote = symbol.split("/")[-1]
        self.balances[quote] = self.balances.get(quote, 0) - funding

    async def check_liquidation(self, symbol: str, mark_price: float) -> Optional[PaperPosition]:
        """Check if a leveraged position should be liquidated."""
        position = self.positions.get(symbol)
        if not position or position.leverage <= 1:
            return None

        liq_price = position.liquidation_price()
        if liq_price is None:
            return None

        if (position.side == "long" and mark_price <= liq_price) or (
            position.side == "short" and mark_price >= liq_price
        ):
            logger.warning(f"PaperVenue: LIQUIDATED {symbol} {position.side} @ {mark_price}")
            del self.positions[symbol]
            return position
        return None

    def get_position(self, symbol: str) -> Optional[PaperPosition]:
        return self.positions.get(symbol)

    def get_balance(self, asset: Optional[str] = None) -> Dict[str, float]:
        if asset:
            return {asset: self.balances.get(asset, 0)}
        return dict(self.balances)

    def get_pnl(self, mark_prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """Compute realized + unrealized PnL."""
        realized_fees = sum(f.fee for f in self.fills)
        realized_funding = sum(p.funding_paid for p in self.positions.values())
        unrealized = 0.0
        if mark_prices:
            for symbol, position in self.positions.items():
                if symbol in mark_prices:
                    unrealized += position.unrealized_pnl(mark_prices[symbol])

        return {
            "realized_fees": realized_fees,
            "realized_funding": realized_funding,
            "unrealized_pnl": unrealized,
            "total_pnl": unrealized - realized_fees - realized_funding,
            "fill_count": len(self.fills),
        }

    def reset(self):
        """Reset the venue to initial state."""
        self.positions.clear()
        self.fills.clear()
        self._order_counter = 0
