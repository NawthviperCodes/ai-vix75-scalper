# === breaker_block_detector.py ===
import pandas as pd

MIN_BODY_RATIO = 0.4  # Require a decent candle body (not a doji)
MIN_WICK_RATIO = 1.5  # Strong wick needed for confirmation

def detect_breaker_block(df: pd.DataFrame, use_body_only=False, lookback=15):
    """
    Detect breaker blocks based on market structure shift and breaker candle.
    Returns a dictionary if found, otherwise None.
    """
    if len(df) < lookback:
        return None

    # Only check the last 5 candles for efficiency
    start_index = max(0, len(df) - 5)
    for i in range(start_index, len(df)):
        candle = df.iloc[i]
        if i == 0:  # Skip first candle
            continue
            
        prev_candle = df.iloc[i - 1]

        body = abs(candle['close'] - candle['open'])
        range_ = candle['high'] - candle['low']

        # Skip indecisive candles
        if range_ == 0 or body / range_ < MIN_BODY_RATIO:
            continue

        upper_wick = candle['high'] - max(candle['close'], candle['open'])
        lower_wick = min(candle['close'], candle['open']) - candle['low']

        is_bullish = candle['close'] > candle['open']
        is_bearish = candle['close'] < candle['open']

        # Detect Bullish Breaker
        if (
            is_bullish and
            lower_wick > body * MIN_WICK_RATIO and
            candle['low'] < prev_candle['low'] and
            candle['close'] > prev_candle['high']
        ):
            zone_top = max(candle['close'], candle['open'])
            zone_bottom = candle['low'] if not use_body_only else min(candle['close'], candle['open'])
            return {
                "type": "bullish",
                "zone_top": zone_top,
                "zone_bottom": zone_bottom,
                "breaker_line": (zone_top + zone_bottom) / 2,
                "valid": True,
                "index": i,
                "time": candle['time']
            }

        # Detect Bearish Breaker
        if (
            is_bearish and
            upper_wick > body * MIN_WICK_RATIO and
            candle['high'] > prev_candle['high'] and
            candle['close'] < prev_candle['low']
        ):
            zone_bottom = min(candle['close'], candle['open'])
            zone_top = candle['high'] if not use_body_only else max(candle['close'], candle['open'])
            return {
                "type": "bearish",
                "zone_top": zone_top,
                "zone_bottom": zone_bottom,
                "breaker_line": (zone_top + zone_bottom) / 2,
                "valid": True,
                "index": i,
                "time": candle['time']
            }

    return None