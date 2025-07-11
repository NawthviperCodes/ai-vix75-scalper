# === symbol_info_helper.py ===

import MetaTrader5 as mt5

def get_lot_constraints(symbol):
    info = mt5.symbol_info(symbol)
    if not info:
        return 0.001, 1.0, 0.001  # Fallback values
    return info.volume_min, info.volume_max, info.volume_step

def print_symbol_lot_info(symbol):
    info = mt5.symbol_info(symbol)
    if not info:
        print(f"[ERROR] Could not retrieve info for {symbol}")
        return

    print(f"\n=== {symbol} Trading Specs ===")
    print(f"Min Lot Size  : {info.volume_min}")
    print(f"Max Lot Size  : {info.volume_max}")
    print(f"Lot Step Size : {info.volume_step}")
    print(f"Contract Size : {info.trade_contract_size}")
    # 🔥 Remove or comment this line (invalid):
    # print(f"Margin Mode   : {info.margin_mode}")  ❌ Invalid
