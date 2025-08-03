# === trade_executor.py (VIX75 Optimized) ===
import MetaTrader5 as mt5
from telegram_notifier import send_telegram_message
from symbol_info_helper import get_symbol_specs

# VIX75-Specific Constants
VIX75_CONFIG = {
    'min_sl_distance': 15000,    # Reduced from 75000 to account for spread
    'tp_ratio': 1.2,
    'fallback_stops': 15000,     # Reduced from 75000
    'trailing_trigger': 5000,
    'trailing_step': 2000,
    'min_tp_distance': 20000,    # Added minimum TP distance
    'spread_buffer': 5000        # Added spread buffer
}

# Defaults for other instruments
DEFAULT_CONFIG = {
    'min_sl_distance': 30000,
    'tp_ratio': 1.5,
    'fallback_stops': 30000,
    'trailing_trigger': 3000,
    'trailing_step': 1000
}

def get_config(symbol):
    """Returns appropriate config based on symbol"""
    specs = get_symbol_specs(symbol)
    if not specs:
        return DEFAULT_CONFIG
    
    if "Volatility 75" in symbol:
        return {
            'min_sl_distance': max(15000, specs['stops_level']),
            'tp_ratio': 1.2,
            'fallback_stops': max(15000, specs['stops_level']),
            'trailing_trigger': 5000,
            'trailing_step': 2000,
            'min_tp_distance': 20000,
            'spread_buffer': 5000
        }
    return DEFAULT_CONFIG

def validate_lot(symbol_info, lot):
    """Validates lot size against broker requirements"""
    min_lot = symbol_info.volume_min
    max_lot = symbol_info.volume_max
    lot_step = symbol_info.volume_step

    if lot < min_lot:
        return round(min_lot, 3)
    if lot > max_lot:
        return round(max_lot, 3)
    return round(round(lot / lot_step) * lot_step, 3)

# Update the place_order function
def place_order(symbol, order_type, lot, sl_price=None, tp_price=None, magic_number=9999, atr=None):
    """Enhanced order placement with VIX75-specific safeguards"""
    config = get_config(symbol)
    symbol_info = mt5.symbol_info(symbol)
    
    if not symbol_info:
        send_telegram_message(f"❌ Symbol {symbol} not found")
        return None

    # Get symbol specifications safely
    try:
        point = symbol_info.point
        digits = symbol_info.digits
        spread = symbol_info.spread * point
        stops_level = getattr(symbol_info, 'stops_level', config['fallback_stops']) * point
    except AttributeError as e:
        send_telegram_message(f"❌ Symbol info error: {str(e)}")
        return None

    spread_buffer = config.get('spread_buffer', 0) * point
    
    # Get current tick data
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        send_telegram_message("❌ Failed to get tick data")
        return None

    price = tick.ask if order_type == "buy" else tick.bid
    lot = validate_lot(symbol_info, lot)

    # Check for existing similar active trades
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for pos in positions:
            if pos.type == (mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL):
                if abs(pos.price_open - price) < 5000 * point:
                    send_telegram_message("🛑 Similar active trade exists — skipping order")
                    return None

    # Handle stop levels with spread consideration
    stops_level = max(stops_level, spread + spread_buffer)  # Ensure stops_level accounts for spread
    
    # Calculate minimum distances
    min_sl_distance = max(
        config['min_sl_distance'] * point,
        stops_level * 1.5  # 1.5x broker requirement
    )
    min_tp_distance = max(
        config.get('min_tp_distance', min_sl_distance * config['tp_ratio']) * point,
        stops_level * 2.0  # TP needs more buffer
    )

    # Process Stop Loss with spread adjustment
    if sl_price is None:
        sl_distance = max(min_sl_distance, (atr or 0) * 1.5)
        sl_price = price - sl_distance if order_type == "buy" else price + sl_distance
    else:
        # Enforce minimum SL distance with spread
        current_sl_distance = abs(price - sl_price)
        if current_sl_distance < min_sl_distance:
            new_sl = price - min_sl_distance if order_type == "buy" else price + min_sl_distance
            send_telegram_message(f"⚠️ Adjusted SL to {new_sl:.2f} (min {min_sl_distance/point:.0f}pts)")
            sl_price = new_sl

    # Process Take Profit with spread adjustment
    if tp_price is None:
        tp_distance = max(min_tp_distance, abs(price - sl_price) * config['tp_ratio'])
        tp_price = price + tp_distance if order_type == "buy" else price - tp_distance
    else:
        # Enforce minimum TP distance
        current_tp_distance = abs(tp_price - price)
        if current_tp_distance < min_tp_distance:
            new_tp = price + min_tp_distance if order_type == "buy" else price - min_tp_distance
            send_telegram_message(f"⚠️ Adjusted TP to {new_tp:.2f}")
            tp_price = new_tp

    # Final validation with spread check
    if abs(price - sl_price) < min_sl_distance:
        send_telegram_message(f"❌ Order skipped: SL needs {min_sl_distance/point:.0f}+ pts (current: {abs(price-sl_price)/point:.0f})")
        return None
        
    if abs(price - tp_price) < min_tp_distance:
        send_telegram_message(f"❌ Order skipped: TP needs {min_tp_distance/point:.0f}+ pts (current: {abs(price-tp_price)/point:.0f})")
        return None

    # Prepare trade request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if order_type == "buy" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": round(sl_price, digits),
        "tp": round(tp_price, digits),
        "deviation": 20,
        "magic": magic_number,
        "comment": "VIX75 Scalper" if "Volatility 75" in symbol else "Auto-trade",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    # Execute trade with enhanced error handling
    try:
        result = mt5.order_send(request)
        if result:
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                msg = (f"✅ {order_type.upper()} {symbol} @ {price:.2f}\n"
                       f"SL: {sl_price:.2f} | TP: {tp_price:.2f} | Lot: {lot}\n"
                       f"Spread: {spread/point:.0f}pts")
                send_telegram_message(msg)
            else:
                error_msg = mt5.return_string(result.retcode)
                details = (f"Price: {price:.2f} | SL: {sl_price:.2f} | TP: {tp_price:.2f}\n"
                          f"Spread: {spread/point:.0f}pts | Stops Level: {stops_level/point:.0f}pts\n"
                          f"Min SL: {min_sl_distance/point:.0f}pts | Min TP: {min_tp_distance/point:.0f}pts")
                send_telegram_message(f"❌ Trade failed (Code: {result.retcode} - {error_msg})\n{details}")
        return result
    except Exception as e:
        send_telegram_message(f"❌ Trade execution error: {str(e)}")
        return None


def trail_sl(symbol, magic):
    """VIX75-optimized trailing stop"""
    config = get_config(symbol)
    positions = mt5.positions_get(symbol=symbol) or []
    
    for pos in positions:
        if pos.magic != magic:
            continue

        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            continue

        # Get current prices
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue

        current_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask
        direction = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
        point = symbol_info.point
        
        # Calculate profit in points
        profit_points = (current_price - pos.price_open) * direction / point
        
        # Check if we should trail
        if profit_points > config['trailing_trigger']:
            new_sl = pos.price_open + (profit_points - config['trailing_step']) * direction * point
            
            # Enforce minimum stop distance
            min_sl = pos.price_open + config['min_sl_distance'] * direction * point
            if (direction == 1 and new_sl < min_sl) or (direction == -1 and new_sl > min_sl):
                new_sl = min_sl
                send_telegram_message(f"⚠️ Trail SL clamped to {min_sl:.2f}")

            # Only update if improvement
            if ((direction == 1 and new_sl > pos.sl) or 
                (direction == -1 and new_sl < pos.sl)):
                
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": round(new_sl, symbol_info.digits),
                    "tp": pos.tp
                })
                
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    send_telegram_message(f"🔰 Trailed SL to {new_sl:.2f}")
