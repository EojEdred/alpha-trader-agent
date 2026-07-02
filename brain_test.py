"""
Brain CLI - Test the Inference Engine directly

Usage:
    python brain_test.py SPY
    python brain_test.py EUR_USD
"""

import asyncio
import sys
import json
from loguru import logger
from tools.brain import reason_about_setup, deep_research_critique

async def main():
    if len(sys.argv) < 2:
        print("Usage: python brain_test.py SYMBOL")
        return

    symbol = sys.argv[1]
    print(f"\n🧠 Testing Dexter's Brain for {symbol}...")

    # Simulated Data
    market_data = {"last_price": 550.0}
    technicals = {"trend": "bullish", "rsi": 62}
    volume_profile = {"poc": 548.5, "fva_low": 545.0, "fva_high": 552.0}
    order_flow = {"cvd_state": "confirming"}

    # 1. Initial Reasoning
    decision = await reason_about_setup(
        symbol=symbol,
        market_data=market_data,
        volume_profile=volume_profile,
        order_flow=order_flow,
        technicals=technicals,
        pdt_status=True
    )

    print("\n--- 🧠 JUNIOR ANALYZED ---")
    print(json.dumps(decision, indent=2))

    # 2. Deep Research Critique
    if decision.get('direction') != 'none':
        critique = await deep_research_critique(
            symbol=symbol,
            brain_decision=decision,
            ohlcv_data=[],
            technicals=technicals
        )
        print("\n--- 🧐 SENIOR CRITIQUE ---")
        print(json.dumps(critique, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
