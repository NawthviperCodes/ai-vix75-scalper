# === zone_detector.py (Fixed Import) ===
import pandas as pd

def detect_zones(df, lookback=100, zone_size=5):
    """
    Detect strong supply and demand zones (pivot-based)
    """
    demand_zones = []
    supply_zones = []

    for i in range(zone_size, len(df) - zone_size):
        candle = df.iloc[i]
        prev_candles = df.iloc[i - zone_size:i]
        next_candles = df.iloc[i + 1:i + 1 + zone_size]

        # Strict Demand Zone (pivot low)
        if (
            all(candle.low < x.low for x in prev_candles.itertuples()) and
            all(candle.low < x.low for x in next_candles.itertuples())
        ):
            demand_zones.append({
                "type": "demand",
                "price": candle.low,
                "time": candle.time
            })

        # Strict Supply Zone (pivot high)
        if (
            all(candle.high > x.high for x in prev_candles.itertuples()) and
            all(candle.high > x.high for x in next_candles.itertuples())
        ):
            supply_zones.append({
                "type": "supply",
                "price": candle.high,
                "time": candle.time
            })

    return demand_zones, supply_zones


def detect_fast_zones(df, proximity=15000):
    """
    Detect fast zones (price rejection zones near live price)
    """
    fast_demand = []
    fast_supply = []

    last_candle = df.iloc[-1]
    recent_candles = df.tail(5)

    # Fast Demand Zone (bullish rejection)
    if any(c.low < last_candle.low + proximity for c in recent_candles.itertuples()):
        fast_demand.append({
            "type": "fast_demand",
            "price": last_candle.low,
            "time": last_candle.time
        })

    # Fast Supply Zone (bearish rejection)
    if any(c.high > last_candle.high - proximity for c in recent_candles.itertuples()):
        fast_supply.append({
            "type": "fast_supply",
            "price": last_candle.high,
            "time": last_candle.time
        })

    return fast_demand, fast_supply
