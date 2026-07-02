"""
Analysis Tools - Process data into signals

Implements:
- calculate_technicals
- analyze_options_greeks
- evaluate_sentiment
- detect_patterns
- calculate_correlations
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger

try:
    import pandas as pd
    import numpy as np
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas/numpy not installed - analysis limited")

try:
    import ta
    TA_AVAILABLE = True
except ImportError:
    TA_AVAILABLE = False
    logger.warning("ta library not installed - technical analysis limited")


def map_session_liquidity(
    ohlcv_data: List[Dict],
    session_times: Dict[str, Dict] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Identifies Session Highs/Lows and Untested Levels.
    
    Session Times (UTC):
    - Asia: 00:00 - 08:00
    - London: 08:00 - 16:00
    - NY: 13:00 - 21:00
    """
    if not ohlcv_data:
        return {}

    # Basic mapping of highs and lows in the data provided
    highs = [b['high'] for b in ohlcv_data]
    lows = [b['low'] for b in ohlcv_data]
    
    # Untested levels are peaks/valleys that the current price hasn't revisited
    # For now, we take the most recent local extremes
    result = {
        'session_extremes': {
            'recent_high': max(highs[-20:]),
            'recent_low': min(lows[-20:]),
            'global_high': max(highs),
            'global_low': min(lows)
        },
        'untested_targets': [max(highs[:-5]), min(lows[:-5])], # Placeholder logic
        'timestamp': datetime.utcnow().isoformat()
    }
    
    return result

def calculate_technicals(
    ohlcv_data: List[Dict] = None,
    indicators: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate technical analysis indicators.

    Indicators: sma_20, sma_50, ema_12, ema_26, rsi_14, macd, bbands, atr
    """
    if indicators is None:
        indicators = ["sma_20", "sma_50", "rsi_14", "macd"]

    logger.info(f"Calculating technicals: {indicators}")

    result = {
        'indicators': {},
        'signals': [],
        'trend': 'neutral',
        'timestamp': datetime.utcnow().isoformat()
    }

    if not PANDAS_AVAILABLE or not ohlcv_data:
        return result

    try:
        # Convert to DataFrame
        df = pd.DataFrame(ohlcv_data)

        if 'close' not in df.columns:
            return result

        # Calculate requested indicators
        for ind in indicators:
            if ind == 'sma_20':
                result['indicators']['sma_20'] = df['close'].rolling(20).mean().iloc[-1]
            elif ind == 'sma_50':
                result['indicators']['sma_50'] = df['close'].rolling(50).mean().iloc[-1]
            elif ind == 'rsi_14':
                if TA_AVAILABLE:
                    result['indicators']['rsi_14'] = ta.momentum.rsi(df['close'], window=14).iloc[-1]
                else:
                    # Simple RSI calculation
                    delta = df['close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / loss
                    result['indicators']['rsi_14'] = (100 - (100 / (1 + rs))).iloc[-1]
            elif ind == 'macd':
                ema12 = df['close'].ewm(span=12).mean()
                ema26 = df['close'].ewm(span=26).mean()
                macd_line = ema12 - ema26
                signal_line = macd_line.ewm(span=9).mean()
                result['indicators']['macd'] = {
                    'macd': macd_line.iloc[-1],
                    'signal': signal_line.iloc[-1],
                    'histogram': (macd_line - signal_line).iloc[-1]
                }

        # Generate simple signals
        last_close = df['close'].iloc[-1]
        sma20 = result['indicators'].get('sma_20', last_close)
        sma50 = result['indicators'].get('sma_50', last_close)
        rsi = result['indicators'].get('rsi_14', 50)

        if last_close > sma20 > sma50:
            result['trend'] = 'bullish'
            result['signals'].append({'type': 'trend', 'direction': 'up', 'strength': 0.7})
        elif last_close < sma20 < sma50:
            result['trend'] = 'bearish'
            result['signals'].append({'type': 'trend', 'direction': 'down', 'strength': 0.7})

        if rsi < 30:
            result['signals'].append({'type': 'rsi', 'condition': 'oversold', 'value': rsi})
        elif rsi > 70:
            result['signals'].append({'type': 'rsi', 'condition': 'overbought', 'value': rsi})

    except Exception as e:
        logger.error(f"Technical analysis error: {e}")
        result['error'] = str(e)

    return result


def detect_daily_reversal_pattern(
    ohlcv_data: List[Dict],
    **kwargs
) -> Dict[str, Any]:
    """
    Detect daily-chart reversal patterns (bullish / bearish).

    Looks for:
    - 3 consecutive red/green days
    - Price testing a recent swing low/high
    - Hammer / shooting-star / doji-style candle on the latest bar

    Returns a signal dict with confidence 0-100.
    """
    neutral = {
        "signal": "neutral",
        "confidence": 0,
        "direction": "none",
        "setup": "No clear reversal pattern",
        "support_level": None,
        "resistance_level": None,
        "reasons": [],
    }

    if not PANDAS_AVAILABLE or not ohlcv_data or len(ohlcv_data) < 10:
        return neutral

    try:
        df = pd.DataFrame(ohlcv_data)
        # Normalize column names
        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            return neutral

        # Ensure numeric
        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=required)
        if len(df) < 10:
            return neutral

        # Use the last 4 complete candles: prior 3 + current forming
        last = df.iloc[-1]
        prev1 = df.iloc[-2]
        prev2 = df.iloc[-3]
        prev3 = df.iloc[-4]

        recent_window = df.tail(20)
        support = float(recent_window["low"].min())
        resistance = float(recent_window["high"].max())

        # Helpers
        def body(c):
            return abs(c["close"] - c["open"])

        def lower_wick(c):
            return min(c["close"], c["open"]) - c["low"]

        def upper_wick(c):
            return c["high"] - max(c["close"], c["open"])

        def is_red(c):
            return c["close"] < c["open"]

        def is_green(c):
            return c["close"] > c["open"]

        # Bullish reversal setup
        three_red = is_red(prev1) and is_red(prev2) and is_red(prev3)
        near_support = last["low"] <= support * 1.005 or last["close"] <= support * 1.01
        hammer = lower_wick(last) >= 1.5 * body(last) and upper_wick(last) <= body(last)
        bullish_current = is_green(last)

        # Bearish reversal setup
        three_green = is_green(prev1) and is_green(prev2) and is_green(prev3)
        near_resistance = last["high"] >= resistance * 0.995 or last["close"] >= resistance * 0.99
        shooting_star = upper_wick(last) >= 1.5 * body(last) and lower_wick(last) <= body(last)
        bearish_current = is_red(last)

        score = 0
        reasons = []
        direction = "none"
        setup = ""

        if three_red:
            score += 25
            reasons.append("3 consecutive red days")
        if near_support:
            score += 30
            reasons.append(f"price testing recent support ${support:.2f}")
        if hammer:
            score += 25
            reasons.append("hammer / skinny-bottom candle")
        if bullish_current:
            score += 20
            reasons.append("current candle bullish")

        if score >= 60:
            direction = "long"
            setup = "bullish reversal at support"
            logger.info(f"Daily reversal signal: {setup} (confidence {score})")
            return {
                "signal": "bullish_reversal",
                "confidence": score,
                "direction": direction,
                "setup": setup,
                "support_level": support,
                "resistance_level": resistance,
                "reasons": reasons,
            }

        # Reset for bearish
        score = 0
        reasons = []

        if three_green:
            score += 25
            reasons.append("3 consecutive green days")
        if near_resistance:
            score += 30
            reasons.append(f"price testing recent resistance ${resistance:.2f}")
        if shooting_star:
            score += 25
            reasons.append("shooting-star candle")
        if bearish_current:
            score += 20
            reasons.append("current candle bearish")

        if score >= 60:
            direction = "short"
            setup = "bearish reversal at resistance"
            logger.info(f"Daily reversal signal: {setup} (confidence {score})")
            return {
                "signal": "bearish_reversal",
                "confidence": score,
                "direction": direction,
                "setup": setup,
                "support_level": support,
                "resistance_level": resistance,
                "reasons": reasons,
            }

        return neutral

    except Exception as e:
        logger.error(f"Daily reversal detection error: {e}")
        return neutral


def analyze_options_greeks(
    options_chain: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Analyze options Greeks and flow.
    """
    logger.info("Analyzing options Greeks")

    result = {
        'aggregate_delta': 0.0,
        'aggregate_gamma': 0.0,
        'put_call_ratio': 0.0,
        'max_pain': 0.0,
        'signals': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    if not options_chain:
        return result

    # Placeholder - implement full Greeks analysis
    return result


async def evaluate_sentiment(
    texts: List[str] = None,
    news_data: Dict = None,
    prediction_market_data: Dict = None,
    sentiment_scores: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Evaluate sentiment from multiple sources.

    In production, use LLM for sophisticated sentiment analysis.
    """
    logger.info("Evaluating sentiment")

    result = {
        'composite_score': 0.0,  # -1 to 1
        'confidence': 0.0,
        'sources': {},
        'signals': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    scores = []

    # News sentiment
    if sentiment_scores:
        result['sources']['news'] = sentiment_scores.get('overall_score', 0)
        scores.append(sentiment_scores.get('overall_score', 0))

    # Prediction market implied sentiment
    if prediction_market_data and 'markets' in prediction_market_data:
        # Simple: if markets exist, neutral sentiment
        result['sources']['prediction_markets'] = 0.0
        scores.append(0.0)

    # Calculate composite
    if scores:
        result['composite_score'] = sum(scores) / len(scores)
        result['confidence'] = min(len(scores) / 5, 1.0)  # More sources = more confidence

    # Generate signals
    if result['composite_score'] > 0.5:
        result['signals'].append({
            'type': 'sentiment',
            'direction': 'bullish',
            'strength': result['composite_score']
        })
    elif result['composite_score'] < -0.5:
        result['signals'].append({
            'type': 'sentiment',
            'direction': 'bearish',
            'strength': abs(result['composite_score'])
        })

    return result


def detect_patterns(
    ohlcv_data: List[Dict] = None,
    technical_signals: Dict = None,
    options_flow_signals: Dict = None,
    composite_sentiment: Dict = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Detect chart patterns and signal convergence.
    """
    logger.info("Detecting patterns")

    result = {
        'patterns': [],
        'convergence_score': 0.0,
        'signals': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    # Collect all signals
    all_signals = []

    if technical_signals and 'signals' in technical_signals:
        all_signals.extend(technical_signals['signals'])

    if options_flow_signals and 'signals' in options_flow_signals:
        all_signals.extend(options_flow_signals['signals'])

    if composite_sentiment and 'signals' in composite_sentiment:
        all_signals.extend(composite_sentiment['signals'])

    # Calculate convergence
    bullish_signals = sum(1 for s in all_signals if s.get('direction') in ['up', 'bullish'])
    bearish_signals = sum(1 for s in all_signals if s.get('direction') in ['down', 'bearish'])

    total_signals = bullish_signals + bearish_signals
    if total_signals > 0:
        result['convergence_score'] = (bullish_signals - bearish_signals) / total_signals

    # Generate pattern signals
    if abs(result['convergence_score']) > 0.5:
        direction = 'bullish' if result['convergence_score'] > 0 else 'bearish'
        result['signals'].append({
            'type': 'convergence',
            'direction': direction,
            'strength': abs(result['convergence_score']),
            'signal_count': total_signals
        })

    result['patterns'] = all_signals

    return result


def calculate_correlations(
    data: Dict[str, List] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Calculate cross-asset correlations.
    """
    logger.info("Calculating correlations")

    result = {
        'correlation_matrix': {},
        'anomalies': [],
        'timestamp': datetime.utcnow().isoformat()
    }

    if not PANDAS_AVAILABLE or not data:
        return result

    # Placeholder - implement correlation analysis


def analyze_premarket_reversal_setup(
    ohlcv_data: List[Dict],
    bb_window: int = 20,
    bb_devs: List[float] = None,
    volume_lookback: int = 20,
    min_volume_ratio: float = 1.0,
    strategy: str = "mean_reversion",
    **kwargs
) -> Dict[str, Any]:
    """
    Bollinger Bands + VWAP + volume analysis.

    Think-or-Swim style interpretation:
    - Blue middle line = VWAP (or BB middle band).
    - Red/purple bands above/below = standard-deviation extensions.
    - When price pushes through the outer bands on elevated volume, the move can
      either revert to the mean (mean_reversion) or keep running (breakout).
      "both" mode uses VWAP as the trend arbiter: it trades BB extremes in the
      direction of the prevailing trend.

    Args:
        strategy: "mean_reversion" (fade the BB touch), "breakout" (follow the
                  BB break), or "both" (use VWAP trend to pick direction).

    Returns a signal dict that can confirm, fade, or veto a trade.
    """
    if bb_devs is None:
        bb_devs = [1.0, 2.0, 3.0]

    neutral = {
        "signal": "neutral",
        "direction": "none",
        "strength": 0.0,
        "score_modifier": 0,
        "vwap": None,
        "bb_middle": None,
        "bb_bands": {},
        "volume_ratio": None,
        "reasons": ["insufficient data"],
        "timestamp": datetime.utcnow().isoformat(),
    }

    if not PANDAS_AVAILABLE or not ohlcv_data or len(ohlcv_data) < bb_window + 5:
        return neutral

    try:
        df = pd.DataFrame(ohlcv_data)
        df.columns = [str(c).lower() for c in df.columns]
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            return neutral

        for col in required:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=required)
        if len(df) < bb_window + 5:
            return neutral

        # VWAP (cumulative typical price * volume / cumulative volume)
        typical = (df["high"] + df["low"] + df["close"]) / 3.0
        df["tp_vol"] = typical * df["volume"]
        df["vwap"] = df["tp_vol"].cumsum() / df["volume"].cumsum()

        # Bollinger Bands at multiple standard deviations
        df["sma"] = df["close"].rolling(window=bb_window).mean()
        df["std"] = df["close"].rolling(window=bb_window).std()

        bands = {}
        for dev in bb_devs:
            bands[f"upper_{dev}"] = (df["sma"] + dev * df["std"]).iloc[-1]
            bands[f"lower_{dev}"] = (df["sma"] - dev * df["std"]).iloc[-1]

        # Volume ratio: last *completed* bar vs recent average.
        # yfinance's final 1m row is often the in-progress candle with 0 volume,
        # so we use the second-to-last row as the "current" volume.
        current_volume = df["volume"].iloc[-2] if len(df) > 1 else df["volume"].iloc[-1]
        recent_volume = df["volume"].iloc[-(volume_lookback + 1):-1].mean()
        volume_ratio = (
            current_volume / recent_volume if recent_volume and recent_volume > 0 else 1.0
        )

        last_close = float(df["close"].iloc[-1])
        vwap = float(df["vwap"].iloc[-1])
        sma = float(df["sma"].iloc[-1])

        # Determine how extended price is relative to the bands
        upper_1 = bands.get("upper_1.0")
        upper_2 = bands.get("upper_2.0")
        upper_3 = bands.get("upper_3.0")
        lower_1 = bands.get("lower_1.0")
        lower_2 = bands.get("lower_2.0")
        lower_3 = bands.get("lower_3.0")

        reasons = []
        signal = "neutral"
        extension = 0  # +1 upper 1st band, +2 upper 2nd, +3 upper 3rd, -1 lower 1st, etc.
        strength = 0.0

        # Volume must be elevated for the signal to be reliable
        volume_confirmed = volume_ratio >= min_volume_ratio

        # Overbought / very overbought (price above upper bands)
        if upper_2 is not None and last_close > upper_2:
            signal = "overbought"
            if upper_3 is not None and last_close > upper_3:
                extension = 3
                strength = 1.0
                reasons.append(f"price above 3rd upper band ({last_close:.2f} > {upper_3:.2f})")
            else:
                extension = 2
                strength = 0.7
                reasons.append(f"price above 2nd upper band ({last_close:.2f} > {upper_2:.2f})")
        elif upper_1 is not None and last_close > upper_1:
            signal = "overbought"
            extension = 1
            strength = 0.4
            reasons.append(f"price above 1st upper band ({last_close:.2f} > {upper_1:.2f})")

        # Oversold / very oversold (price below lower bands)
        elif lower_2 is not None and last_close < lower_2:
            signal = "oversold"
            if lower_3 is not None and last_close < lower_3:
                extension = -3
                strength = 1.0
                reasons.append(f"price below 3rd lower band ({last_close:.2f} < {lower_3:.2f})")
            else:
                extension = -2
                strength = 0.7
                reasons.append(f"price below 2nd lower band ({last_close:.2f} < {lower_2:.2f})")
        elif lower_1 is not None and last_close < lower_1:
            signal = "oversold"
            extension = -1
            strength = 0.4
            reasons.append(f"price below 1st lower band ({last_close:.2f} < {lower_1:.2f})")
        else:
            reasons.append(f"price inside BB envelope ({last_close:.2f}, VWAP={vwap:.2f})")

        # Map extension to trade direction and score modifier based on strategy
        direction = "none"
        score_modifier = 0
        if extension != 0:
            if strategy == "breakout":
                # Follow the break: upper band = long, lower band = short
                direction = "long" if extension > 0 else "short"
                raw_modifier = abs(extension) * 10
                score_modifier = raw_modifier if direction == "long" else -raw_modifier
            elif strategy == "both":
                # Use VWAP trend to decide: trade BB extremes in trend direction
                uptrend = last_close > vwap
                if extension > 0:
                    # Above upper band: go long in uptrend (breakout), short in downtrend (reversion)
                    direction = "long" if uptrend else "short"
                else:
                    # Below lower band: go short in downtrend (breakdown), long in uptrend (bounce)
                    direction = "short" if not uptrend else "long"
                raw_modifier = abs(extension) * 10
                score_modifier = raw_modifier if direction == "long" else -raw_modifier
                reasons.append(f"VWAP trend {'up' if uptrend else 'down'} → {direction}")
            else:
                # Mean reversion: fade the extreme
                direction = "short" if extension > 0 else "long"
                raw_modifier = abs(extension) * 10
                score_modifier = raw_modifier if direction == "long" else -raw_modifier

        # Volume attenuation: weak volume = unreliable signal
        if not volume_confirmed:
            score_modifier = int(score_modifier * 0.3)
            reasons.append(f"volume ratio {volume_ratio:.2f}x below threshold {min_volume_ratio}")
        else:
            reasons.append(f"volume confirmed ({volume_ratio:.2f}x recent avg)")

        # VWAP agreement: price on the same side as the breakout (or opposite for reversion)
        # strengthens the read
        if signal == "overbought" and last_close > vwap:
            if strategy == "breakout":
                reasons.append("price above VWAP (agrees with breakout up)")
            elif strategy == "both":
                reasons.append("price above VWAP (uptrend context)")
            else:
                reasons.append("price above VWAP (agrees with overbought)")
            strength = min(strength + 0.1, 1.0)
        elif signal == "oversold" and last_close < vwap:
            if strategy == "breakout":
                reasons.append("price below VWAP (agrees with breakout down)")
            elif strategy == "both":
                reasons.append("price below VWAP (downtrend context)")
            else:
                reasons.append("price below VWAP (agrees with oversold)")
            strength = min(strength + 0.1, 1.0)

        return {
            "signal": signal,
            "direction": direction,
            "strength": round(strength, 2),
            "score_modifier": score_modifier,
            "vwap": round(vwap, 4),
            "bb_middle": round(sma, 4),
            "bb_bands": {k: round(v, 4) for k, v in bands.items()},
            "volume_ratio": round(volume_ratio, 2),
            "last_close": round(last_close, 4),
            "reasons": reasons,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        logger.error(f"Premarket reversal analysis error: {e}")
        return {**neutral, "reasons": [f"analysis error: {e}"]}
    return result
