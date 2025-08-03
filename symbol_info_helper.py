# === symbol_info_helper.py ===

import MetaTrader5 as mt5
from telegram_notifier import send_telegram_message

# List of safe attributes that exist for all symbols
SAFE_ATTRIBUTES = [
    'volume_min', 'volume_max', 'volume_step',
    'point', 'digits', 'spread', 'trade_contract_size'
]

def get_lot_constraints(symbol):
    """Get min, max, and step size for lot trading"""
    info = mt5.symbol_info(symbol)
    if not info:
        send_telegram_message(f"❌ Could not get symbol info for {symbol}", priority="high")
        return 0.001, 1.0, 0.001  # Fallback values
    return info.volume_min, info.volume_max, info.volume_step

def get_symbol_specs(symbol):
    """Get all relevant trading specifications for a symbol"""
    info = mt5.symbol_info(symbol)
    if not info:
        send_telegram_message(f"❌ Could not get symbol info for {symbol}", priority="high")
        return None
    
    specs = {}
    for attr in SAFE_ATTRIBUTES:
        try:
            specs[attr] = getattr(info, attr)
        except AttributeError:
            # Set reasonable defaults if attribute missing
            defaults = {
                'trade_contract_size': 1.0,
                'point': 0.01,
                'digits': 2
            }
            specs[attr] = defaults.get(attr, 0)
    
    # Special handling for stops_level
    try:
        specs['stops_level'] = info.stops_level
    except AttributeError:
        specs['stops_level'] = 10770  # Default for VIX75
        send_telegram_message(f"⚠️ Using default stops_level (10770) for {symbol}", priority="normal")
    
    return specs

def print_symbol_lot_info(symbol):
    """Print formatted symbol information for debugging"""
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"[ERROR] Could not retrieve info for {symbol}")
        return

    print(f"\n=== {symbol} Trading Specs ===")
    
    # Only print attributes we know exist
    for attr in SAFE_ATTRIBUTES:
        try:
            value = getattr(info, attr)
            label = attr.replace('_', ' ').title()
            suffix = ' points' if attr == 'spread' else ''
            print(f"{label.ljust(18)}: {value}{suffix}")
        except AttributeError:
            continue
    
    # Special handling for stops_level
    try:
        print(f"Stops Level       : {info.stops_level} points")
    except AttributeError:
        print("Stops Level       : Not available (using default 10770)")