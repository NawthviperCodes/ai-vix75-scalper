# === zone_detector.py (Enhanced with Dynamic Threshold Logic) ===

import pandas as pd
import uuid

# === Dynamic Zone Threshold Settings ===
USE_DYNAMIC_ZONE_THRESHOLD = True
MIN_ZONE_STRENGTH = 25  # fallback floor strength (never accept below this)

def get_dynamic_zone_threshold(df):
    atr = (df['high'] - df['low']).rolling(14).mean()
    atr_avg = atr.iloc[-20:].mean() if len(atr) >= 20 else 0
    scaled_score = atr_avg * 0.002  # scale ATR to zone score range
    return max(MIN_ZONE_STRENGTH, min(100, scaled_score))


def score_zone(base_candles, breakout_candle):
    avg_candle_size = base_candles['high'] - base_candles['low']
    avg_candle_size = avg_candle_size.mean()
    breakout_size = breakout_candle.high - breakout_candle.low

    size_score = min(100, (breakout_size / avg_candle_size) * 15)
    base_time_score = max(0, 30 - len(base_candles) * 3)
    wick_penalty = 10 if abs(breakout_candle.close - breakout_candle.open) < abs(breakout_candle.high - breakout_candle.low) * 0.3 else 0

    raw_score = size_score + base_time_score - wick_penalty
    return max(10, min(100, raw_score))


def score_fast_zone(candle):
    body = abs(candle.close - candle.open)
    total = candle.high - candle.low
    upper_wick = candle.high - max(candle.close, candle.open)
    lower_wick = min(candle.close, candle.open) - candle.low

    wick_ratio = max(upper_wick, lower_wick) / body if body != 0 else 0
    size_score = min(40, (total / body) * 10) if body > 0 else 0
    wick_score = min(40, wick_ratio * 10)

    raw_score = 10 + size_score + wick_score
    return int(min(100, max(10, raw_score)))


def has_round_number(price, threshold=50):
    return price % 1000 < threshold or price % 1000 > 1000 - threshold


def is_marubozu(candle):
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.close, candle.open)
    lower_wick = min(candle.close, candle.open) - candle.low
    return upper_wick < body * 0.1 and lower_wick < body * 0.1


def detect_zones(df, lookback=150, zone_size=6, min_score=40, buffer_points=1000):
    demand_zones = []
    supply_zones = []

    dynamic_threshold = get_dynamic_zone_threshold(df) if USE_DYNAMIC_ZONE_THRESHOLD else min_score

    for i in range(zone_size, len(df) - zone_size):
        candle = df.iloc[i]
        prev_candles = df.iloc[i - zone_size:i]
        next_candles = df.iloc[i + 1:i + 1 + zone_size]

        zone_score = score_zone(prev_candles, candle)
        is_key_level = has_round_number(candle.low)

        if all(candle.low < x.low for x in prev_candles.itertuples()) and all(candle.low < x.low for x in next_candles.itertuples()):
            if zone_score >= dynamic_threshold:
                demand_zones.append({
                    "id": str(uuid.uuid4()),
                    "type": "strict_demand",
                    "low": candle.low,
                    "high": max(candle.open, candle.close),
                    "price": (candle.low + max(candle.open, candle.close)) / 2,
                    "buffered_sl": candle.low - buffer_points,
                    "buffered_tp": max(candle.open, candle.close) + 2 * buffer_points,
                    "time": candle.time,
                    "touches": 0,
                    "strength": zone_score + (5 if is_marubozu(candle) else 0) + (5 if is_key_level else 0),
                    "fresh": True
                })

        if all(candle.high > x.high for x in prev_candles.itertuples()) and all(candle.high > x.high for x in next_candles.itertuples()):
            if zone_score >= dynamic_threshold:
                supply_zones.append({
                    "id": str(uuid.uuid4()),
                    "type": "strict_supply",
                    "low": min(candle.open, candle.close),
                    "high": candle.high,
                    "price": (min(candle.open, candle.close) + candle.high) / 2,
                    "buffered_sl": candle.high + buffer_points,
                    "buffered_tp": min(candle.open, candle.close) - 2 * buffer_points,
                    "time": candle.time,
                    "touches": 0,
                    "strength": zone_score + (5 if is_marubozu(candle) else 0) + (5 if is_key_level else 0),
                    "fresh": True
                })

    demand_zones = merge_overlapping_zones(demand_zones)
    supply_zones = merge_overlapping_zones(supply_zones)

    return demand_zones, supply_zones


def merge_overlapping_zones(zones):
    if not zones:
        return []

    zones = sorted(zones, key=lambda z: z['low'])
    merged = [zones[0]]

    for z in zones[1:]:
        last = merged[-1]
        if z['low'] <= last['high']:
            merged[-1] = {
                "id": last['id'],
                "type": last['type'],
                "low": min(last['low'], z['low']),
                "high": max(last['high'], z['high']),
                "price": (min(last['low'], z['low']) + max(last['high'], z['high'])) / 2,
                "buffered_sl": min(last['buffered_sl'], z['buffered_sl']),
                "buffered_tp": max(last['buffered_tp'], z['buffered_tp']),
                "time": z['time'],
                "touches": 0,
                "strength": max(last['strength'], z['strength']),
                "fresh": True
            }
        else:
            merged.append(z)
    return merged


def detect_fast_zones(df, proximity=10000, min_body_ratio=0.3):
    fast_demand = []
    fast_supply = []
    recent_candles = df.tail(4)

    for candle in recent_candles.itertuples():
        body_size = abs(candle.close - candle.open)
        total_size = candle.high - candle.low
        if total_size == 0:
            continue
        body_ratio = body_size / total_size

        score = score_fast_zone(candle)
        print(f"[DEBUG] Fast zone check | Time: {candle.time} | Body: {body_size:.2f} | Total: {total_size:.2f} | Score: {score}")

        if score < 50:
            continue

        if body_ratio < min_body_ratio and candle.low < df.iloc[-1].low + proximity:
            fast_demand.append({
                "id": str(uuid.uuid4()),
                "type": "fast_demand",
                "low": candle.low,
                "high": candle.close,
                "price": (candle.low + candle.close) / 2,
                "buffered_sl": candle.low - 1000,
                "buffered_tp": candle.close + 2000,
                "time": candle.time,
                "touches": 0,
                "strength": score,
                "fresh": True
            })

        if body_ratio < min_body_ratio and candle.high > df.iloc[-1].high - proximity:
            fast_supply.append({
                "id": str(uuid.uuid4()),
                "type": "fast_supply",
                "low": candle.close,
                "high": candle.high,
                "price": (candle.close + candle.high) / 2,
                "buffered_sl": candle.high + 1000,
                "buffered_tp": candle.close - 2000,
                "time": candle.time,
                "touches": 0,
                "strength": score,
                "fresh": True
            })

    return fast_demand, fast_supply
