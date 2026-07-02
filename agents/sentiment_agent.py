"""
Sentiment Browser Agent

Uses browser automation to scan social media and news for sentiment on tickers.
Inspired by TradingAgents' Sentiment Analyst.

Sources scanned:
- Reddit (r/wallstreetbets, r/algotrading, r/stocks, r/options)
- StockTwits (trending symbols)
- Yahoo Finance news headlines
- Twitter/X (if accessible)

Returns: AnalystReport with bullish/bearish/neutral direction + confidence.

Usage:
    from agents.sentiment_agent import SentimentAgent

    agent = SentimentAgent()
    report = await agent.analyze("SPY")
    print(report.direction, report.confidence)
"""

import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from loguru import logger

from models.decision_schemas import AnalystReport, Direction, Confidence


class SentimentAgent:
    """Browser-based sentiment analysis agent."""

    name = "sentiment_analyst"
    description = "Scans Reddit, StockTwits, and news for social sentiment"

    # Sentiment keywords
    BULLISH_WORDS = [
        "bull", "bullish", "moon", "rocket", "tendies", "calls", "long",
        "buy", "undervalued", "cheap", "rally", "breakout", "gamma squeeze",
        "all time high", "ath", "pump", "hodl", "diamond hands", "yolo",
    ]
    BEARISH_WORDS = [
        "bear", "bearish", "crash", "dump", "puts", "short", "sell",
        "overvalued", "expensive", "bubble", "recession", "correction",
        "rug pull", "paper hands", "panic", "fear", "bloodbath", "capitulation",
    ]

    def __init__(self, model=None):
        self.model = model  # Optional LLM for summarization

    async def analyze(self, symbol: str) -> AnalystReport:
        """
        Analyze sentiment for a symbol across multiple sources.

        Returns AnalystReport with direction and confidence.
        """
        logger.info(f"SentimentAgent analyzing {symbol}")

        # Gather data from multiple sources
        reddit_posts = await self._scan_reddit(symbol)
        stocktwits_posts = await self._scan_stocktwits(symbol)
        news_headlines = await self._scan_news(symbol)

        # Combine all text
        all_text = "\n".join(reddit_posts + stocktwits_posts + news_headlines)

        # Count sentiment indicators
        bullish_count = sum(1 for word in self.BULLISH_WORDS if word in all_text.lower())
        bearish_count = sum(1 for word in self.BEARISH_WORDS if word in all_text.lower())
        total = bullish_count + bearish_count

        # Calculate confidence and direction
        if total == 0:
            direction = Direction.NEUTRAL
            confidence = 0.5
            conviction = Confidence.LOW
            key_points = ["No clear sentiment signals found"]
        else:
            bullish_pct = bullish_count / total
            bearish_pct = bearish_count / total

            if bullish_pct > 0.6:
                direction = Direction.LONG
                confidence = min(bullish_pct, 0.95)
                conviction = Confidence.HIGH if bullish_pct > 0.8 else Confidence.MEDIUM
                key_points = [
                    f"Bullish mentions: {bullish_count}",
                    f"Bearish mentions: {bearish_count}",
                    f"Bullish ratio: {bullish_pct:.0%}",
                ]
            elif bearish_pct > 0.6:
                direction = Direction.SHORT
                confidence = min(bearish_pct, 0.95)
                conviction = Confidence.HIGH if bearish_pct > 0.8 else Confidence.MEDIUM
                key_points = [
                    f"Bearish mentions: {bearish_count}",
                    f"Bullish mentions: {bullish_count}",
                    f"Bearish ratio: {bearish_pct:.0%}",
                ]
            else:
                direction = Direction.NEUTRAL
                confidence = 0.5
                conviction = Confidence.LOW
                key_points = [
                    f"Mixed sentiment (bullish: {bullish_count}, bearish: {bearish_count})",
                ]

        risks = [
            "Social sentiment can change rapidly",
            "Retail sentiment may be contrarian indicator",
            "Sample size may be small for less-discussed symbols",
        ]

        # If LLM available, generate a richer summary
        reasoning = self._generate_reasoning(symbol, direction, confidence, reddit_posts, stocktwits_posts, news_headlines)

        return AnalystReport(
            agent_name=self.name,
            symbol=symbol,
            direction=direction,
            confidence=confidence,
            conviction_level=conviction,
            key_points=key_points,
            risks=risks,
            timeframe="1-3 days",
            evidence={
                "reddit_posts_scanned": len(reddit_posts),
                "stocktwits_posts_scanned": len(stocktwits_posts),
                "news_headlines_scanned": len(news_headlines),
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
            },
            reasoning=reasoning,
        )

    async def _scan_reddit(self, symbol: str) -> List[str]:
        """Scan Reddit for mentions of the symbol."""
        try:
            import aiohttp
            posts = []

            # Try to fetch from Reddit JSON API (no auth needed for public posts)
            subreddits = ["wallstreetbets", "stocks", "algotrading", "options", "daytrading"]

            async with aiohttp.ClientSession() as session:
                for sub in subreddits:
                    url = f"https://www.reddit.com/r/{sub}/search.json?q={symbol}&restrict_sr=1&sort=new&limit=5"
                    try:
                        async with session.get(url, headers={"User-Agent": "AlphaTrader/1.0"}, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for post in data.get("data", {}).get("children", []):
                                    title = post.get("data", {}).get("title", "")
                                    selftext = post.get("data", {}).get("selftext", "")[:200]
                                    if title or selftext:
                                        posts.append(f"{title} {selftext}")
                    except Exception:
                        pass

            return posts[:20]  # Limit to 20 posts

        except Exception as e:
            logger.warning(f"Reddit scan failed for {symbol}: {e}")
            return []

    async def _scan_stocktwits(self, symbol: str) -> List[str]:
        """Scan StockTwits for symbol mentions."""
        try:
            import aiohttp
            posts = []

            async with aiohttp.ClientSession() as session:
                url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json?limit=10"
                try:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for msg in data.get("messages", []):
                                body = msg.get("body", "")
                                if body:
                                    posts.append(body)
                except Exception:
                    pass

            return posts[:15]

        except Exception as e:
            logger.warning(f"StockTwits scan failed for {symbol}: {e}")
            return []

    async def _scan_news(self, symbol: str) -> List[str]:
        """Scan Yahoo Finance news for headlines."""
        try:
            import aiohttp
            headlines = []

            async with aiohttp.ClientSession() as session:
                # Yahoo Finance news RSS
                url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
                try:
                    async with session.get(url, timeout=5) as resp:
                        if resp.status == 200:
                            text = await resp.text()
                            # Extract titles from RSS
                            titles = re.findall(r"<title>(.*?)</title>", text)
                            headlines.extend(titles[1:])  # Skip first (channel title)
                except Exception:
                    pass

            return headlines[:10]

        except Exception as e:
            logger.warning(f"News scan failed for {symbol}: {e}")
            return []

    def _generate_reasoning(self, symbol: str, direction: Direction, confidence: float,
                            reddit: List[str], stocktwits: List[str], news: List[str]) -> str:
        """Generate a natural language summary of the sentiment analysis."""
        source_summary = []
        if reddit:
            source_summary.append(f"Reddit: {len(reddit)} posts analyzed")
        if stocktwits:
            source_summary.append(f"StockTwits: {len(stocktwits)} messages analyzed")
        if news:
            source_summary.append(f"News: {len(news)} headlines analyzed")

        sources = ", ".join(source_summary) if source_summary else "Limited data available"

        direction_str = direction.value.upper()

        if direction == Direction.NEUTRAL:
            return (
                f"Sentiment analysis for {symbol} shows mixed signals. "
                f"{sources}. No clear bullish or bearish consensus detected. "
                f"Social media discussion is either balanced or insufficient for a strong read."
            )

        return (
            f"Sentiment analysis for {symbol} indicates a {direction_str} bias "
            f"with {confidence:.0%} confidence. {sources}. "
            f"Social sentiment aligns with a {direction_str} directional view."
        )
