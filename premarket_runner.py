import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

from tools.options_multi_scalper import run_premarket_gap_entry

async def main():
    print("Running pre-market gap entry analysis...")
    print("=" * 60)
    result = await run_premarket_gap_entry()
    
    entries = result.get("entries", [])
    errors = result.get("errors", [])
    
    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  - {e}")
    
    if not entries:
        print("\nNo pre-market gap entries triggered.")
        print("Possible reasons: gaps below 0.30% threshold, market closed, or data unavailable.")
        return
    
    print(f"\n{len(entries)} PRE-MARKET GAP ENTRY SIGNAL(S):")
    print("=" * 60)
    for i, entry in enumerate(entries, 1):
        print(f"\nTrade #{i}")
        print(f"  Underlying:    {entry.get('underlying')}")
        print(f"  Gap:           {entry.get('gap_pct', 0):+.2f}%")
        print(f"  Option Symbol: {entry.get('option_symbol')}")
        print(f"  Direction:     {entry.get('direction')}")
        print(f"  Quantity:      {entry.get('quantity')}")
        print(f"  Limit Price:   ${entry.get('limit_price', 0):.2f}")
        print(f"  Score:         {entry.get('score')}")
        print(f"  Thesis:        {entry.get('thesis', '')}")
        order = entry.get('order_result', {})
        print(f"  Order Status:  {order.get('status', 'N/A')}")
        if order.get('error'):
            print(f"  Order Error:   {order.get('error')}")
    
    print("\n" + "=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
