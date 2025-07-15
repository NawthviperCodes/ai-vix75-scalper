# === trend_filter.py ===

import MetaTrader5 as mt5
import pandas as pd

def calculate_ema(data, period):
    return data['close'].ewm(span=period, adjust=False).mean()

def get_trend(symbol, timeframe=mt5.TIMEFRAME_M5, num_candles=50):
    if not mt5.initialize():
        raise Exception("Failed to initialize MT5")

    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
    if rates is None or len(rates) < 20:
        return "neutral"

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')

    df['ema_5'] = calculate_ema(df, 5)
    df['ema_20'] = calculate_ema(df, 20)

    # Compare the most recent EMAs
    latest_ema5 = df['ema_5'].iloc[-1]
    latest_ema20 = df['ema_20'].iloc[-1]

    if latest_ema5 > latest_ema20:
        return "uptrend"
    elif latest_ema5 < latest_ema20:
        return "downtrend"
    else:
        return "neutral"
