"""
Market Data Tools - Fetch data from various sources

Implements:
- fetch_options_chain (IB/Schwab)
- fetch_futures_data (NinjaTrader)
- fetch_crypto_data (CCXT)
- fetch_polymarket (Polymarket API)
- fetch_news (NewsAPI)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from loguru import logger

# These will be imported when available
try:
    import ccxt.async_support as ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    logger.warning("CCXT not installed - crypto data unavailable")

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


async def fetch_options_chain(
    symbol: str = None,
    watchlist: List[str] = None,
    expiration_range_days: int = 60,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetch options chain data for symbols.

    In production, this would connect to Interactive Brokers or Schwab API.
    For now, returns placeholder structure.
    """
    symbols = watchlist or (config.options_watchlist if config else ["SPY"])
    if symbol:
        symbols = [symbol]

    logger.info(f"Fetching options chain for {len(symbols)} symbols")

    # Placeholder - implement with ib_insync or schwab-api
    result = {
        'symbols_fetched': symbols,
        'data_quality_score': 0.95,
        'unusual_activity_count': 0,
        'chains': {},
        'timestamp': datetime.utcnow().isoformat()
    }

    for sym in symbols:
        result['chains'][sym] = {
            'underlying_price': 0.0,  # Would be real price
            'calls': [],
            'puts': [],
            'iv_rank': 0.0,
        }

    return result


async def fetch_futures_data(
    contract: str = None,
    futures_watchlist: List[str] = None,
    config: Any = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """
    Fetch futures OHLCV data.

    Uses the live TopstepX / ProjectX Gateway for supported futures symbols
    (NQ, ES, MNQ, MES, YM, CL, GC) and falls back to Yahoo Finance only when
    the gateway is unavailable. This avoids stale Yahoo data that was causing
    the auto-scalper to sit out valid setups.
    """
    contracts = futures_watchlist or (config.futures_watchlist if config else ["ES", "NQ"])
    if contract:
        contracts = [contract]

    c = contracts[0].upper()
    logger.info(f"Fetching futures data for {c}")

    # ─── Primary: live TopstepX / ProjectX Gateway bars ───
    topstep_supported = {"NQ", "ES", "MNQ", "MES", "YM", "CL", "GC"}
    if c in topstep_supported:
        try:
            from tools.topstep import topstep_get_bars, TOPSTEP_AVAILABLE
            if TOPSTEP_AVAILABLE:
                candles = await topstep_get_bars(c, days=1, interval=5)
                if candles:
                    logger.info(f"Fetched {len(candles)} live TopstepX candles for {c}")
                    return candles
                else:
                    logger.warning(f"TopstepX returned no bars for {c}; falling back")
        except Exception as e:
            logger.warning(f"TopstepX futures data fetch failed for {c}: {e}; falling back")

    # ─── Fallback: Yahoo Finance ───
    yahoo_map = {
        "NQ": "NQ=F", "ES": "ES=F", "YM": "YM=F", "CL": "CL=F", "GC": "GC=F",
        "SPY": "SPY", "QQQ": "QQQ", "TSLA": "TSLA",
    }
    yahoo_sym = yahoo_map.get(c, c)

    try:
        import yfinance as yf
        ticker = yf.Ticker(yahoo_sym)
        hist = ticker.history(period="5d", interval="5m")
        if not hist.empty:
            candles = []
            for idx, row in hist.iterrows():
                candles.append({
                    'timestamp': idx.isoformat(),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume']),
                })
            logger.info(f"Fetched {len(candles)} Yahoo candles for {c}")
            return candles
    except Exception as e:
        logger.warning(f"Yahoo fetch failed for {c}: {e}")

    # Fallback placeholder
    return [{'timestamp': datetime.utcnow().isoformat(), 'open': 0.0, 'high': 0.0, 'low': 0.0, 'close': 0.0, 'volume': 0}]


async def fetch_crypto_data(
    exchange: str = "binance",
    symbol: str = None,
    crypto_watchlist: List[str] = None,
    timeframe: str = "1h",
    limit: int = 100,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetch cryptocurrency data via CCXT.
    """
    if not CCXT_AVAILABLE:
        logger.warning("CCXT not available")
        return {'status': 'unavailable', 'reason': 'ccxt_not_installed'}

    symbols = crypto_watchlist or (config.crypto_watchlist if config else ["BTC/USDT"])
    if symbol:
        symbols = [symbol]

    logger.info(f"Fetching crypto data from {exchange} for {symbols}")

    result = {
        'exchange': exchange,
        'symbols_fetched': symbols,
        'data': {},
        'funding_rates': {},
        'timestamp': datetime.utcnow().isoformat()
    }

    try:
        exchange_class = getattr(ccxt, exchange)
        ex = exchange_class({'enableRateLimit': True})

        for sym in symbols:
            try:
                ohlcv = await ex.fetch_ohlcv(sym, timeframe, limit=limit)
                result['data'][sym] = {
                    'ohlcv': [
                        {
                            'timestamp': candle[0],
                            'open': candle[1],
                            'high': candle[2],
                            'low': candle[3],
                            'close': candle[4],
                            'volume': candle[5]
                        }
                        for candle in ohlcv[-20:]  # Last 20 candles
                    ],
                    'last_price': ohlcv[-1][4] if ohlcv else 0,
                }
            except Exception as e:
                logger.warning(f"Failed to fetch {sym}: {e}")
                result['data'][sym] = {'error': str(e)}

        await ex.close()

    except Exception as e:
        logger.error(f"CCXT error: {e}")
        result['error'] = str(e)

    return result


async def fetch_polymarket(
    market_id: str = None,
    polymarket_watchlist: List[str] = None,
    active_only: bool = True,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetch prediction market data from Polymarket.
    """
    if not AIOHTTP_AVAILABLE:
        return {'status': 'unavailable', 'reason': 'aiohttp_not_installed'}

    logger.info("Fetching Polymarket data")

    base_url = "https://clob.polymarket.com"

    result = {
        'markets': [],
        'mispricing_alerts': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    try:
        async with aiohttp.ClientSession() as session:
            # Fetch markets
            url = f"{base_url}/markets"
            if active_only:
                url += "?active=true"

            async with session.get(url) as resp:
                if resp.status == 200:
                    markets = await resp.json()
                    # Limit to first 50 for demo
                    result['markets'] = markets[:50] if isinstance(markets, list) else []
                else:
                    result['error'] = f"HTTP {resp.status}"

    except Exception as e:
        logger.error(f"Polymarket error: {e}")
        result['error'] = str(e)

    return result


async def fetch_news(
    symbols: List[str] = None,
    news_sources: List[str] = None,
    hours_back: int = 24,
    config: Any = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetch financial news headlines.

    In production, use NewsAPI, Bloomberg, or similar.
    """
    logger.info(f"Fetching news for last {hours_back} hours")

    # Placeholder - implement with real news API
    result = {
        'headlines': [],
        'sentiment_scores': {},
        'timestamp': datetime.utcnow().isoformat()
    }

    return result


async def fetch_current_price(
    symbol: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Fetch current price for a symbol.

    Args:
        symbol: Trading symbol

    Returns:
        Dictionary with price data
    """
    logger.info(f"Fetching current price for {symbol}")

    # If it's a major equity index ETF, use Schwab
    if any(x in symbol.upper() for x in ["SPY", "QQQ", "IWM", "DIA"]):
        try:
            from tools.schwab import schwab_get_price
            price_data = await schwab_get_price(symbol.upper())
            if 'last' in price_data:
                return {
                    'symbol': symbol,
                    'price': price_data['last'],
                    'bid': price_data.get('bid'),
                    'ask': price_data.get('ask'),
                    'timestamp': price_data.get('timestamp')
                }
        except Exception as e:
            logger.warning(f"Schwab price fetch failed for {symbol}: {e}")

    # Fallback to OANDA for gold
    if symbol.upper() in ["XAUUSD", "GOLD", "GC", "XAU"]:
        try:
            from tools.oanda import oanda_get_price
            price_data = await oanda_get_price()
            if 'bid' in price_data:
                return {
                    'symbol': symbol,
                    'price': (price_data['bid'] + price_data['ask']) / 2,
                    'bid': price_data['bid'],
                    'ask': price_data['ask'],
                    'timestamp': price_data.get('time')
                }
        except Exception as e:
            logger.warning(f"OANDA price fetch failed for {symbol}: {e}")

    # Placeholder implementation
    return {
        'symbol': symbol,
        'price': 0.0,  # Placeholder
        'timestamp': datetime.utcnow().isoformat()
    }


async def fetch_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    limit: int = 50,
    **kwargs
) -> List[Dict]:
    """
    Fetch real OHLCV data for a symbol via Yahoo Finance.

    Args:
        symbol: Trading symbol (e.g., 'SPY', 'QQQ', 'TSLA', 'NQ')
        timeframe: Timeframe (e.g., '1m', '5m', '15m', '30m', '1h', '1d')
        limit: Number of candles to return (most recent)

    Returns:
        List of OHLCV dicts with ISO timestamps
    """
    logger.info(f"Fetching {timeframe} OHLCV for {symbol} (limit: {limit})")

    # Map common symbols to Yahoo Finance tickers
    yahoo_map = {
        "NQ": "NQ=F", "ES": "ES=F", "YM": "YM=F",
        "MNQ": "MNQ=F", "MES": "MES=F", "CL": "CL=F", "GC": "GC=F",
    }
    yahoo_symbol = yahoo_map.get(symbol.upper(), symbol.upper())

    # Timeframe -> yfinance period/interval
    tf_cfg = {
        "1m":   ("5d", "1m"),
        "5m":   ("5d", "5m"),
        "15m":  ("5d", "15m"),
        "30m":  ("1mo", "30m"),
        "1h":   ("1mo", "1h"),
        "4h":   ("3mo", "1h"),  # yfinance max hourly ~ 1mo; use daily proxy
        "1d":   ("6mo", "1d"),
    }
    period, interval = tf_cfg.get(timeframe, ("1mo", timeframe))

    try:
        import yfinance as yf
        ticker = yf.Ticker(yahoo_symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            raise ValueError(f"No data returned for {yahoo_symbol}")

        candles = []
        for idx, row in hist.iterrows():
            ts = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
            candles.append({
                "timestamp": ts,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })

        logger.info(f"Fetched {len(candles)} candles for {symbol}")
        return candles[-limit:] if limit and len(candles) > limit else candles
    except Exception as e:
        logger.warning(f"Yahoo Finance fetch failed for {symbol}: {e}")

    # Fallback: empty list so callers can handle gracefully
    return []


async def fetch_sentiment(
    texts: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze sentiment from text data.
    """
    # Placeholder - implement with LLM or sentiment model
    return {
        'overall_score': 0.0,
        'breakdown': {},
        'timestamp': datetime.utcnow().isoformat()
    }
