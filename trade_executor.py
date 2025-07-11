# === Updated trade_executor.py (Fixed SL/TP Validation + Lot Size Step Handling) ===

import MetaTrader5 as mt5
from telegram_notifier import send_telegram_message

FALLBACK_STOPS_LEVEL = 10770  # 107.70 price (2 digits) for VIX75
TRAILING_TRIGGER = 3000
TRAILING_STEP = 1000
TP_RATIO = 2  # Used to calculate TP based on SL


def validate_lot(symbol_info, lot):
    min_lot = symbol_info.volume_min
    max_lot = symbol_info.volume_max
    lot_step = symbol_info.volume_step

    original_lot = lot

    if lot < min_lot:
        print(f"[WARN] Lot size {lot} below min allowed ({min_lot}). Adjusted to minimum.")
        lot = min_lot
    elif lot > max_lot:
        print(f"[WARN] Lot size {lot} above max allowed ({max_lot}). Adjusted to maximum.")
        lot = max_lot
    elif round((lot - min_lot) % lot_step, 6) != 0:
        print(f"[WARN] Lot size {lot} is not a valid step size of {lot_step}. Adjusted to nearest valid step.")

    # Round to nearest step
    lot = round(round(lot / lot_step) * lot_step, 3)

    if lot != original_lot:
        print(f"[INFO] Final validated lot size: {lot}")

    return lot


def place_order(symbol, order_type, lot, sl_price, tp_price, magic_number):
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        print("[ERROR] Symbol info not found.")
        return None

    lot = validate_lot(symbol_info, lot)
    print(f"[DEBUG] Order Requested with Lot Size: {lot}")
    stops_level = getattr(symbol_info, "stops_level", FALLBACK_STOPS_LEVEL)
    point = symbol_info.point
    digits = symbol_info.digits
    
    # Calculate minimal allowed distance (in price)
    min_distance = stops_level * point * 1.2  # Add 20% buffer to stops_level
    min_tp_distance = min_distance * TP_RATIO  # Maintain risk/reward ratio

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print("[ERROR] Failed to get tick.")
        return None

    price = tick.ask if order_type == "buy" else tick.bid
    deviation = 20

    # Validate and adjust SL/TP to meet broker requirements
    if order_type == "buy":
        # Ensure SL is below current price
        if sl_price >= price:
            sl_price = price - min_distance
        
        # Ensure SL distance meets requirement
        if (price - sl_price) < min_distance:
            sl_price = round(price - min_distance, digits)
        
        # Ensure TP distance meets requirement
        if (tp_price - price) < min_tp_distance:
            tp_price = round(price + (price - sl_price) * TP_RATIO, digits)
    else:  # sell
        # Ensure SL is above current price
        if sl_price <= price:
            sl_price = price + min_distance
            
        # Ensure SL distance meets requirement
        if (sl_price - price) < min_distance:
            sl_price = round(price + min_distance, digits)
        
        # Ensure TP distance meets requirement
        if (price - tp_price) < min_tp_distance:
            tp_price = round(price - (sl_price - price) * TP_RATIO, digits)

    # Round to correct digits
    sl_price = round(sl_price, digits)
    tp_price = round(tp_price, digits)
    
    print(f"[DEBUG] Entry: {price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}")
    print(f"[DEBUG] SL distance: {abs(price - sl_price):.2f}, TP distance: {abs(tp_price - price):.2f}")

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": deviation,
        "magic": magic_number,
        "comment": "auto-trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    result = mt5.order_send(request)
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[ERROR] Order failed. Retcode: {result.retcode if result else 'N/A'} | Comment: {result.comment if result else 'No result'}")
    return result


def trail_sl(symbol, magic, profit_threshold=TRAILING_TRIGGER, step=TRAILING_STEP):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return

    for pos in positions:
        if pos.magic != magic:
            continue

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            continue

        point = symbol_info.point
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue

        current_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        entry = pos.price_open
        sl = pos.sl
        if sl is None or sl <= 0:
            continue

        direction = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
        profit_points = (current_price - entry) * direction / point

        if profit_points > profit_threshold:
            new_sl = entry + (profit_points - step) * direction * point
            if (direction == 1 and new_sl > sl) or (direction == -1 and new_sl < sl):
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp,
                }
                result = mt5.order_send(request)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    msg = f"🔐 Trailing SL updated for {symbol} at {new_sl:.2f}"
                    print(msg)
                    send_telegram_message(msg)