# === zone_detector.py (VIX75 Beast Upgrade v2) ===
import pandas as pd
import uuid


def score_zone(base_candles, breakout_candle):
    """
    Calculate strength score (0-100) for a zone.
    - Bigger breakout vs average = higher score
    - Shorter base = stronger
    - Long wicks = penalty
    """
    avg_candle_size = base_candles['high'] - base_candles['low']
    avg_candle_size = avg_candle_size.mean()
    breakout_size = breakout_candle.high - breakout_candle.low

    size_score = min(100, (breakout_size / avg_candle_size) * 15)
    base_time_score = max(0, 30 - len(base_candles) * 3)
    wick_penalty = 10 if abs(breakout_candle.close - breakout_candle.open) < abs(breakout_candle.high - breakout_candle.low) * 0.3 else 0

    raw_score = size_score + base_time_score - wick_penalty
    return max(10, min(100, raw_score))  # Clamp 10-100


def detect_zones(df, lookback=150, zone_size=6, min_score=20):
    """
    Detect demand/supply zones with strength scoring.
    """
    demand_zones = []
    supply_zones = []

    for i in range(zone_size, len(df) - zone_size):
        candle = df.iloc[i]
        prev_candles = df.iloc[i - zone_size:i]
        next_candles = df.iloc[i + 1:i + 1 + zone_size]

        # Demand Zone (pivot low)
        if all(candle.low < x.low for x in prev_candles.itertuples()) and all(candle.low < x.low for x in next_candles.itertuples()):
            zone_low = candle.low
            zone_high = max(candle.open, candle.close)
            strength = score_zone(prev_candles, candle)

            if strength >= min_score:
                demand_zones.append({
                    "id": str(uuid.uuid4()),
                    "type": "strict_demand",
                    "low": zone_low,
                    "high": zone_high,
                    "price": (zone_low + zone_high) / 2,
                    "time": candle.time,
                    "touches": 0,
                    "strength": strength,
                    "fresh": True
                })

        # Supply Zone (pivot high)
        if all(candle.high > x.high for x in prev_candles.itertuples()) and all(candle.high > x.high for x in next_candles.itertuples()):
            zone_high = candle.high
            zone_low = min(candle.open, candle.close)
            strength = score_zone(prev_candles, candle)

            if strength >= min_score:
                supply_zones.append({
                    "id": str(uuid.uuid4()),
                    "type": "strict_supply",
                    "low": zone_low,
                    "high": zone_high,
                    "price": (zone_low + zone_high) / 2,
                    "time": candle.time,
                    "touches": 0,
                    "strength": strength,
                    "fresh": True
                })

    demand_zones = merge_overlapping_zones(demand_zones)
    supply_zones = merge_overlapping_zones(supply_zones)

    return demand_zones, supply_zones


def merge_overlapping_zones(zones):
    """
    Merge overlapping zones into a stronger one.
    """
    if not zones:
        return []

    zones = sorted(zones, key=lambda z: z['low'])
    merged = [zones[0]]

    for z in zones[1:]:
        last = merged[-1]
        if z['low'] <= last['high']:  # Overlap
            merged[-1] = {
                "id": last['id'],
                "type": last['type'],
                "low": min(last['low'], z['low']),
                "high": max(last['high'], z['high']),
                "price": (min(last['low'], z['low']) + max(last['high'], z['high'])) / 2,
                "time": z['time'],
                "touches": 0,
                "strength": max(last['strength'], z['strength']),
                "fresh": True
            }
        else:
            merged.append(z)
    return merged


def detect_fast_zones(df, proximity=10000, min_body_ratio=0.3):
    """
    Detect fast zones based on last few candles' wicks and spikes.
    """
    fast_demand = []
    fast_supply = []
    recent_candles = df.tail(4)

    for candle in recent_candles.itertuples():
        body_size = abs(candle.close - candle.open)
        total_size = candle.high - candle.low
        if total_size == 0:
            continue
        body_ratio = body_size / total_size

        # Fast Demand: large lower wick + small body
        if body_ratio < min_body_ratio and candle.low < df.iloc[-1].low + proximity:
            fast_demand.append({
                "id": str(uuid.uuid4()),
                "type": "fast_demand",
                "low": candle.low,
                "high": candle.close,
                "price": (candle.low + candle.close) / 2,
                "time": candle.time,
                "touches": 0,
                "strength": 50,
                "fresh": True
            })

        # Fast Supply: large upper wick + small body
        if body_ratio < min_body_ratio and candle.high > df.iloc[-1].high - proximity:
            fast_supply.append({
                "id": str(uuid.uuid4()),
                "type": "fast_supply",
                "low": candle.close,
                "high": candle.high,
                "price": (candle.close + candle.high) / 2,
                "time": candle.time,
                "touches": 0,
                "strength": 50,
                "fresh": True
            })

    return fast_demand, fast_supply
