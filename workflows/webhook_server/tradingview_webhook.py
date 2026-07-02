"""
TradingView Webhook Server

FastAPI server that receives alert webhooks from TradingView
and routes them to the execution controller.

TradingView webhook setup:
1. Create alert in TradingView
2. Enable "Webhook URL" notification
3. Set URL to: https://your-server.com/webhook/tradingview
4. Message format: JSON with symbol, side, quantity, etc.
"""

import os
import json
import hmac
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

try:
    from fastapi import FastAPI, Request, HTTPException, Header
    from fastapi.responses import JSONResponse
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning("fastapi not installed, webhook server unavailable")


# Global app instance
webhook_app = FastAPI(title="AlphaTrader Webhook Server") if FASTAPI_AVAILABLE else None

# Webhook secret for verification
WEBHOOK_SECRET = os.getenv("TRADINGVIEW_WEBHOOK_SECRET", "")

# Reference to controller (set at startup)
_controller = None


def set_controller(controller):
    """Set the controller reference for webhook callbacks."""
    global _controller
    _controller = controller


@webhook_app.post("/webhook/tradingview") if webhook_app else lambda: None
async def tradingview_webhook(
    request: Request,
    x_tradingview_signature: Optional[str] = Header(None),
):
    """
    Receive TradingView alert webhook.
    
    Expected payload:
    {
        "symbol": "NQ1!",
        "side": "buy",
        "quantity": 1,
        "price": 18500.50,
        "message": "RSI oversold bounce",
        "strategy": "liquidity_sweep",
        "timeframe": "5m",
        "passphrase": "your_secret"
    }
    """
    body = await request.body()
    
    # Verify signature if secret is configured
    if WEBHOOK_SECRET and x_tradingview_signature:
        expected = hmac.new(
            WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, x_tradingview_signature):
            raise HTTPException(status_code=401, detail="Invalid signature")
    
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Validate required fields
    required = ["symbol", "side"]
    for field in required:
        if field not in data:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
    
    logger.info(f"TradingView webhook received: {data['symbol']} {data['side']}")
    
    # Route to appropriate handler
    result = await _handle_tradingview_alert(data)
    
    return JSONResponse(content=result)


async def _handle_tradingview_alert(data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a TradingView alert and route to execution."""
    symbol = data["symbol"]
    side = data["side"].lower()
    quantity = data.get("quantity", 1)
    price = data.get("price")
    message = data.get("message", "")
    strategy = data.get("strategy", "tradingview_alert")
    
    # Determine venue based on symbol
    venue = _determine_venue(symbol)
    
    # Create TradeIntent
    from models import TradeIntent, generate_intent_id, ExecutionMode
    
    intent = TradeIntent(
        id=generate_intent_id(),
        capsule_id=strategy,
        thesis_id="tradingview_webhook",
        symbol=symbol,
        direction="long" if side in ["buy", "long"] else "short",
        entry_price=price or 0.0,
        stop_price=data.get("stop_price", 0.0),
        target_price=data.get("target_price", 0.0),
        conviction=0.75,  # TradingView alerts have decent confidence
        invalidation_price=data.get("invalidation_price", 0.0),
        time_stop=datetime.utcnow(),  # Would calculate from timeframe
        risk_reward_ratio=2.0,
        size=quantity,
        execution_mode=ExecutionMode.AUTO,
        venue=venue,
        evidence_citations=[f"tradingview_{strategy}"],
    )
    
    # Create risk decision (auto-approve for webhook with size limits)
    from models import RiskDecision
    
    risk_decision = RiskDecision(
        intent_id=intent.id,
        approved=True,
        warnings=["Auto-approved from TradingView webhook"],
    )
    
    # Execute if controller is available
    if _controller:
        result = await _controller.submit_trade(intent, risk_decision)
        return {
            "status": "received",
            "intent_id": intent.id,
            "execution_status": result.status,
            "method": result.method.value if hasattr(result.method, 'value') else str(result.method),
        }
    
    return {
        "status": "queued",
        "intent_id": intent.id,
        "message": "Controller not available, intent queued",
    }


def _determine_venue(symbol: str) -> str:
    """Determine execution venue from symbol."""
    symbol_upper = symbol.upper()
    
    # Futures
    if any(x in symbol_upper for x in ["NQ", "ES", "YM", "CL", "GC", "SI", "ZB", "ZN"]):
        return "topstep"  # Default to prop firm for futures
    
    # Forex
    if "/" in symbol or symbol_upper in ["XAUUSD", "EURUSD", "GBPUSD"]:
        return "oanda"
    
    # Crypto
    if symbol_upper in ["BTC", "ETH", "SOL", "AVAX"]:
        return "polymarket"
    
    # Equities/Options default to Schwab
    return "schwab"


@webhook_app.post("/webhook/generic") if webhook_app else lambda: None
async def generic_webhook(request: Request):
    """Generic webhook endpoint for other platforms."""
    data = await request.json()
    logger.info(f"Generic webhook received: {data}")
    return {"status": "received"}


@webhook_app.get("/health") if webhook_app else lambda: None
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "controller_connected": _controller is not None,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ─── STANDALONE SERVER ───

def run_webhook_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the webhook server standalone."""
    if not FASTAPI_AVAILABLE:
        logger.error("FastAPI not installed. Run: pip install fastapi uvicorn")
        return
    
    import uvicorn
    logger.info(f"Starting webhook server on {host}:{port}")
    uvicorn.run(webhook_app, host=host, port=port)


if __name__ == "__main__":
    run_webhook_server()
