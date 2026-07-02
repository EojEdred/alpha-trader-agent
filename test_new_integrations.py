"""
Test script to verify new platform integrations in Alpha Trader system.
"""

import asyncio
import sys
from pathlib import Path

# Add the alpha-trader directory to the path
sys.path.insert(0, str(Path(__file__).parent))

async def test_new_integrations():
    """Test all newly added platform integrations."""
    print("Testing new platform integrations...\n")
    
    # Test PrizePicks integration
    print("1. Testing PrizePicks integration...")
    try:
        from tools.prizepicks import (
            prizepicks_get_projections, 
            prizepicks_get_leagues, 
            prizepicks_get_contests
        )
        
        # Test functions exist and can be imported
        print("   ✓ PrizePicks functions imported successfully")
        
        # Test getting projections (this will fail without API keys but should not crash)
        projections = await prizepicks_get_projections()
        print(f"   ✓ PrizePicks get_projections executed (returned {len(projections.get('projections', []))} items)")
        
        leagues = await prizepicks_get_leagues()
        print(f"   ✓ PrizePicks get_leagues executed (returned {len(leagues.get('leagues', []))} items)")
        
        contests = await prizepicks_get_contests()
        print(f"   ✓ PrizePicks get_contests executed (returned {len(contests.get('contests', []))} items)")
        
        print("   ✓ PrizePicks integration test completed\n")
    except Exception as e:
        print(f"   ✗ PrizePicks integration test failed: {e}\n")
    
    # Test BetMGM integration
    print("2. Testing BetMGM integration...")
    try:
        from tools.betmgm import (
            betmgm_get_sports,
            betmgm_get_events,
            betmgm_get_markets
        )
        
        print("   ✓ BetMGM functions imported successfully")
        
        sports = await betmgm_get_sports()
        print(f"   ✓ BetMGM get_sports executed (returned {len(sports.get('sports', []))} items)")
        
        print("   ✓ BetMGM integration test completed\n")
    except Exception as e:
        print(f"   ✗ BetMGM integration test failed: {e}\n")
    
    # Test FanDuel integration
    print("3. Testing FanDuel integration...")
    try:
        from tools.fanduel import (
            fanduel_get_sports,
            fanduel_get_events,
            fanduel_get_markets
        )
        
        print("   ✓ FanDuel functions imported successfully")
        
        sports = await fanduel_get_sports()
        print(f"   ✓ FanDuel get_sports executed (returned {len(sports.get('sports', []))} items)")
        
        print("   ✓ FanDuel integration test completed\n")
    except Exception as e:
        print(f"   ✗ FanDuel integration test failed: {e}\n")
    
    # Test Panda Forex integration
    print("4. Testing Panda Forex integration...")
    try:
        from tools.pandafx import (
            pandafx_get_pairs,
            pandafx_get_quotes,
            pandafx_get_positions
        )
        
        print("   ✓ PandaFX functions imported successfully")
        
        pairs = await pandafx_get_pairs()
        print(f"   ✓ PandaFX get_pairs executed (returned {len(pairs.get('pairs', []))} items)")
        
        quotes = await pandafx_get_quotes()
        print(f"   ✓ PandaFX get_quotes executed (returned {len(quotes.get('quotes', {}))} items)")
        
        positions = await pandafx_get_positions()
        print(f"   ✓ PandaFX get_positions executed (returned {len(positions)} items)")
        
        print("   ✓ Panda Forex integration test completed\n")
    except Exception as e:
        print(f"   ✗ Panda Forex integration test failed: {e}\n")
    
    # Test Apex Funded Futures integration
    print("5. Testing Apex Funded Futures integration...")
    try:
        from tools.apexfutures import (
            apexfutures_get_contracts,
            apexfutures_get_quotes,
            apexfutures_get_positions
        )
        
        print("   ✓ ApexFutures functions imported successfully")
        
        contracts = await apexfutures_get_contracts()
        print(f"   ✓ ApexFutures get_contracts executed (returned {len(contracts.get('contracts', []))} items)")
        
        quotes = await apexfutures_get_quotes()
        print(f"   ✓ ApexFutures get_quotes executed (returned {len(quotes.get('quotes', {}))} items)")
        
        positions = await apexfutures_get_positions()
        print(f"   ✓ ApexFutures get_positions executed (returned {len(positions)} items)")
        
        print("   ✓ Apex Funded Futures integration test completed\n")
    except Exception as e:
        print(f"   ✗ Apex Funded Futures integration test failed: {e}\n")
    
    # Test tool registry integration
    print("6. Testing tool registry integration...")
    try:
        import yaml
        tool_registry_path = Path(__file__).parent / "tools" / "tool_registry.yaml"
        with open(tool_registry_path, 'r') as f:
            registry = yaml.safe_load(f)
        
        # Check if new tools are in the registry
        tool_names = [tool['id'] for tool in registry['tools']]
        
        new_tools = [
            'prizepicks_get_projections', 'prizepicks_get_leagues', 'prizepicks_get_contests',
            'betmgm_get_sports', 'betmgm_get_events', 'betmgm_get_markets',
            'fanduel_get_sports', 'fanduel_get_events', 'fanduel_get_markets',
            'pandafx_get_pairs', 'pandafx_get_quotes', 'pandafx_get_positions',
            'apexfutures_get_contracts', 'apexfutures_get_quotes', 'apexfutures_get_positions'
        ]
        
        missing_tools = [tool for tool in new_tools if tool not in tool_names]
        
        if not missing_tools:
            print("   ✓ All new tools found in tool registry")
        else:
            print(f"   ⚠ Missing tools in registry: {missing_tools}")
        
        print("   ✓ Tool registry integration test completed\n")
    except Exception as e:
        print(f"   ✗ Tool registry integration test failed: {e}\n")
    
    print("Integration testing completed!")


if __name__ == "__main__":
    asyncio.run(test_new_integrations())