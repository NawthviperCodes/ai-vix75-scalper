# === trend_filter.py (Precision Scalping Version) ===

import MetaTrader5 as mt5
import pandas as pd
import numpy as np

def get_trend(symbol, timeframe=mt5.TIMEFRAME_M15, num_candles=100, sma_period=44):
    if not mt5.initialize():
        raise Exception("Failed to initialize MT5")

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
    if rates is None or len(rates) < sma_period + 5:
        return "neutral"

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df['sma'] = df['close'].rolling(sma_period).mean()

    recent_sma = df['sma'].iloc[-5:]
    sma_slope = (recent_sma.iloc[-1] - recent_sma.iloc[0]) / sma_period

    highs = df['high'].iloc[-5:].tolist()
    lows = df['low'].iloc[-5:].tolist()
    last_price = df['close'].iloc[-1]
    last_sma = df['sma'].iloc[-1]

    # Structure check
    higher_highs = all(x < y for x, y in zip(highs, highs[1:]))
    higher_lows = all(x < y for x, y in zip(lows, lows[1:]))
    lower_highs = all(x > y for x, y in zip(highs, highs[1:]))
    lower_lows = all(x > y for x, y in zip(lows, lows[1:]))

    # Slope threshold: only count SMA as valid if it's clearly rising/falling
    slope_threshold = 0.01 * last_sma  # ~1% of price
    is_sma_rising = sma_slope > slope_threshold
    is_sma_falling = sma_slope < -slope_threshold

    if higher_highs and higher_lows and last_price > last_sma and is_sma_rising:
        return "uptrend"
    elif lower_highs and lower_lows and last_price < last_sma and is_sma_falling:
        return "downtrend"
    else:
        return "neutral"
