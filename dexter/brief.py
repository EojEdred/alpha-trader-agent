"""
Dexter Brief Generator
"""
from datetime import datetime
from typing import Dict, List
import asyncio
from loguru import logger
from tools.scoring import score_setup
from tools.arbitrage import scan_arbitrage
from tools.reporting import generate_report

async def generate_brief(target_date: datetime) -> Dict:
    """
    Generate morning trading brief using real data and A+ scoring.
    
    Args:
        target_date: Date for the brief
        
    Returns:
        Dictionary with brief data
    """
    logger.info(f"Generating morning brief for {target_date.strftime('%Y-%m-%d')}")
    
    # Symbols to analyze
    watchlist = ["SPY", "QQQ"]
    
    # 1. Score setups
    setups = []
    for symbol in watchlist:
        try:
            score_result = await score_setup(symbol)
            if score_result.trade_allowed:
                # Calculate basic targets/stops for the brief
                price_data = score_result.notes[0] # Usually contains location/price info
                
                # Create a simplified setup object for the brief
                setups.append({
                    'symbol': symbol,
                    'direction': 'long' if score_result.total > 50 else 'short', # Heuristic
                    'grade': score_result.grade.value,
                    'score': score_result.total,
                    'entry': 0, # Would be current price
                    'stop': 0,
                    'target': 0,
                    'notes': score_result.notes
                })
        except Exception as e:
            logger.error(f"Error scoring {symbol} for brief: {e}")

    # 2. Scan for arbitrage
    arb_opportunities = []
    try:
        arb_opportunities = await scan_arbitrage(min_spread_pct=1.0)
    except Exception as e:
        logger.error(f"Error scanning arbs for brief: {e}")

    # 3. Determine market regime (simplified)
    regime = "Neutral"
    if setups:
        avg_score = sum(s['score'] for s in setups) / len(setups)
        if avg_score > 70:
            regime = "Bullish"
        elif avg_score < 40:
            regime = "Bearish"

    # 4. Generate the report file
    brief_data = {
        'date': target_date.strftime('%Y-%m-%d'),
        'regime': regime,
        'sentiment': sum(s['score'] for s in setups) / 100 if setups else 0.5,
        'setups': setups,
        'arb_opportunities': arb_opportunities
    }

    # Use the existing reporting tool to save to disk
    report_result = generate_report(
        trade_recommendations=setups,
        technical_signals={'trend': regime},
        composite_sentiment={'composite_score': brief_data['sentiment']},
        format="markdown"
    )

    # 5. Delivery via Telegram if configured
    import os
    if os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID'):
        from tools.delivery import send_telegram
        logger.info("Sending morning brief via Telegram")
        
        # Prepare a concise summary for Telegram
        msg = f"🌅 *Morning Brief: {brief_data['date']}*\n\n"
        msg += f"*Regime:* {regime}\n"
        msg += f"*Sentiment:* {brief_data['sentiment']:.2f}\n\n"
        msg += "*Top Setups:*\n"
        for s in setups:
            msg += f"• {s['symbol']}: {s['direction'].upper()} ({s['grade']}) - Score: {s['score']}\n"
        
        if arb_opportunities:
            msg += "\n*Arb Opportunities:*\n"
            for arb in arb_opportunities[:3]:
                msg += f"• {arb.market}: {arb.spread_pct:.2f}% ({arb.platforms})\n"
        
        asyncio.create_task(send_telegram(message=msg))

    brief_data['output_path'] = report_result['report_path']
    return brief_data

    