# === trade_executor.py (Elite VIX75 SL/TP Engine + Trailing Logic) ===

import MetaTrader5 as mt5
from telegram_notifier import send_telegram_message

FALLBACK_STOPS_LEVEL = 10770
TRAILING_TRIGGER = 3000
TRAILING_STEP = 1000
TP_RATIO = 2
ATR_MULTIPLIER = 2.0


def validate_lot(symbol_info, lot):
    min_lot = symbol_info.volume_min
    max_lot = symbol_info.volume_max
    lot_step = symbol_info.volume_step

    if lot < min_lot:
        lot = min_lot
    elif lot > max_lot:
        lot = max_lot
    elif round((lot - min_lot) % lot_step, 6) != 0:
        lot = round(round(lot / lot_step) * lot_step, 3)

    return round(lot, 3)


def place_order(symbol, order_type, lot, sl_price=None, tp_price=None, magic_number=9999, atr=None):
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        send_telegram_message(f"[ERROR] Symbol '{symbol}' not found.")
        return None

    point = symbol_info.point
    digits = symbol_info.digits
    stops_level = symbol_info.stops_level or FALLBACK_STOPS_LEVEL
    min_distance = stops_level * point * 2.5
    min_tp_distance = min_distance * TP_RATIO

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        send_telegram_message("[ERROR] Tick info not found.")
        return None

    price = tick.ask if order_type == "buy" else tick.bid
    lot = validate_lot(symbol_info, lot)
    deviation = 20

    # Dynamic SL if not pre-defined
    if sl_price is None:
        sl_distance = max(min_distance, (atr or 0) * ATR_MULTIPLIER)
        sl_price = price - sl_distance if order_type == "buy" else price + sl_distance

    sl_price = round(sl_price, digits)

    # Dynamic TP based on SL if not pre-defined
    if tp_price is None:
        tp_distance = abs(price - sl_price) * TP_RATIO
        tp_price = price + tp_distance if order_type == "buy" else price - tp_distance

    tp_price = round(tp_price, digits)

    # Final validations
    if abs(price - sl_price) < min_distance:
        send_telegram_message("⚠️ SL too close to entry. Order skipped.")
        return None
    if abs(tp_price - price) < min_tp_distance:
        send_telegram_message("⚠️ TP too close to entry. Order skipped.")
        return None

    print(f"[ORDER] {order_type.upper()} | Entry: {price:.2f}, SL: {sl_price:.2f}, TP: {tp_price:.2f}, Lot: {lot}")
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
        error_msg = f"[ERROR] Order failed. Retcode: {getattr(result, 'retcode', 'N/A')} | Comment: {getattr(result, 'comment', 'No comment')}"
        print(error_msg)
        send_telegram_message(error_msg)
    else:
        send_telegram_message(f"✅ Trade executed: {order_type.upper()} {symbol} @ {price:.2f}")
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
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": round(new_sl, symbol_info.digits),
                    "tp": pos.tp
                })
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    msg = f"🔐 Trailing SL updated for {symbol}: {new_sl:.2f}"
                    print(msg)
                    send_telegram_message(msg)
