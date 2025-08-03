import pandas as pd
import numpy as np

DEBUG_ZONES = False  # Enable this to debug why zones are rejected

def detect_swing_points(df, swing_window=5):
    highs = df['high']
    lows = df['low']
    swing_highs = (highs.shift(swing_window) < highs) & (highs.shift(-swing_window) < highs)
    swing_lows = (lows.shift(swing_window) > lows) & (lows.shift(-swing_window) > lows)
    return swing_highs, swing_lows

def calculate_zone_strength(zone, df, lookback_bars=80):
    past = df[df['time'] < zone['timestamp']].tail(lookback_bars)
    if len(past) == 0:
        return 0

    zone_low = zone['zone_low']
    zone_high = zone['zone_high']

    if zone['zone_type'] == 'demand':
        touches = ((past['low'] <= zone_high) & (past['low'] >= zone_low)).sum()
        held = (past['low'].min() >= zone_low)
        momentum = (past['close'].iloc[-1] > zone_high)
    else:
        touches = ((past['high'] >= zone_low) & (past['high'] <= zone_high)).sum()
        held = (past['high'].max() <= zone_high)
        momentum = (past['close'].iloc[-1] < zone_low)

    strength = (
        25 * held +
        35 * min(touches, 3) +
        40 * momentum
    )
    return min(strength, 100)

def detect_zones(
    df,
    zone_type='demand',
    swing_window=4,
    buffer_pips=35,
    future_confirm=40,
    min_strength=38
):
    zones = []
    df = df.copy()
    
    if 'time' not in df.columns:
        if DEBUG_ZONES:
            print("[ERROR] DataFrame missing 'time' column")
        return [], {"accepted": 0, "rejected": 0, "max": 0}

    swing_highs, swing_lows = detect_swing_points(df, swing_window)

    for i in range(swing_window, len(df) - future_confirm):
        current = df.iloc[i]

        if zone_type == 'demand' and swing_lows.iloc[i]:
            low_index = df['low'].iloc[i - swing_window:i + 1].idxmin()
            local_low = df.loc[low_index, 'low']
            next_candles = df.iloc[i + 1:i + future_confirm]
            valid = next_candles['low'].min() >= local_low - buffer_pips
            
            if valid:
                zone = {
                    'zone_type': 'demand',
                    'zone_low': max(local_low - buffer_pips, 0),
                    'zone_high': current['low'] + buffer_pips,
                    'timestamp': current['time'],
                    'base_candles': swing_window
                }
                zone['strength'] = calculate_zone_strength(zone, df)
                zones.append(zone)
            elif DEBUG_ZONES:
                print(f"[REJECTED] Demand zone at {local_low:.2f} failed hold check. Next low: {next_candles['low'].min():.2f}")

        elif zone_type == 'supply' and swing_highs.iloc[i]:
            high_index = df['high'].iloc[i - swing_window:i + 1].idxmax()
            local_high = df.loc[high_index, 'high']
            next_candles = df.iloc[i + 1:i + future_confirm]
            valid = next_candles['high'].max() <= local_high + buffer_pips
            
            if valid:
                zone = {
                    'zone_type': 'supply',
                    'zone_high': local_high + buffer_pips,
                    'zone_low': max(current['high'] - buffer_pips, 0),
                    'timestamp': current['time'],
                    'base_candles': swing_window
                }
                zone['strength'] = calculate_zone_strength(zone, df)
                zones.append(zone)
            elif DEBUG_ZONES:
                print(f"[REJECTED] Supply zone at {local_high:.2f} failed hold check. Next high: {next_candles['high'].max():.2f}")

    strong_zones = []
    for z in zones:
        if z['strength'] >= min_strength:
            strong_zones.append(z)
        elif DEBUG_ZONES:
            print(f"[FILTERED] {z['zone_type'].upper()} zone {z['zone_low']:.2f}-{z['zone_high']:.2f} rejected due to low strength ({z['strength']}%)")

    if not strong_zones:
        return [], {"accepted": 0, "rejected": len(zones), "max": 0}
    
    merged = []
    sorted_zones = sorted(strong_zones, key=lambda x: x['zone_low'] if x['zone_type'] == 'demand' else x['zone_high'])
    current_zone = sorted_zones[0]
    
    for i in range(1, len(sorted_zones)):
        zone = sorted_zones[i]
        if (current_zone['zone_type'] == zone['zone_type'] and
            current_zone['zone_low'] <= zone['zone_high'] and
            current_zone['zone_high'] >= zone['zone_low']):
            current_zone['zone_low'] = min(current_zone['zone_low'], zone['zone_low'])
            current_zone['zone_high'] = max(current_zone['zone_high'], zone['zone_high'])
            current_zone['strength'] = (current_zone['strength'] + zone['strength']) / 2
            current_zone['merged'] = True
        else:
            merged.append(current_zone)
            current_zone = zone
    merged.append(current_zone)
    
    return merged, {
        "accepted": len(merged),
        "rejected": len(zones) - len(strong_zones),
        "max": max([z['strength'] for z in zones], default=0)
    }
""""
def detect_respected_zones(df, zone_type='demand', min_touches=2):
    zones = detect_zones(df, zone_type=zone_type)[0]
    respected = []

    for zone in zones:
        future = df[df['time'] > zone['timestamp']].head(100)
        if len(future) < 3:
            continue

        if zone['zone_type'] == 'demand':
            touches = ((future['low'] <= zone['zone_high']) & (future['low'] >= zone['zone_low'])).sum()
            held = (future['low'].min() >= zone['zone_low'])
            momentum = (future['close'].iloc[-1] > zone['zone_high'])
        else:
            touches = ((future['high'] >= zone['zone_low']) & (future['high'] <= zone['zone_high'])).sum()
            held = (future['high'].max() <= zone['zone_high'])
            momentum = (future['close'].iloc[-1] < zone['zone_low'])

        if touches >= min_touches and held and momentum:
            respected.append(zone)

    return respected
    
"""

def scan_zones(get_data_func, symbol, timeframe, lookback):
    df = get_data_func(symbol, timeframe, lookback)
    required_columns = ['time', 'open', 'high', 'low', 'close']
    if df.empty or not all(col in df.columns for col in required_columns):
        print(f"[❌ ZONE SCAN] Invalid DataFrame structure for {symbol}")
        return [], []

    demand_raw, demand_stats = detect_zones(df, zone_type='demand')
    supply_raw, supply_stats = detect_zones(df, zone_type='supply')

    demand_zones = []
    supply_zones = []

    for z in demand_raw:
        price = (z['zone_low'] + z['zone_high']) / 2
        demand_zones.append({
            'price': price,
            'type': "strict_demand",
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        })

    for z in supply_raw:
        price = (z['zone_low'] + z['zone_high']) / 2
        supply_zones.append({
            'price': price,
            'type': "strict_supply",
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        })

    return demand_zones, supply_zones
