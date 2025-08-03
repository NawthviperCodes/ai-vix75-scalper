# === scalper_strategy_engine.py ===
# (Enhanced with rate limiting and message consolidation)

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from candlestick_patterns import detect_patterns
from zone_detector import detect_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message, flush_message_queue
from trade_executor import place_order, trail_sl
from performance_tracker import log_trade
from zone_detector import scan_zones
from breaker_block_detector import detect_breaker_block
import os
from trend_filter import get_trend
from dotenv import load_dotenv

load_dotenv()

# === Zone refresh settings ===
ZONE_REFRESH_INTERVAL = 300  # 5 minutes
_last_zone_scan = None
_last_demand_zones = []
_last_supply_zones = []

# --- Configuration
SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
TIMEFRAME_PATTERN = mt5.TIMEFRAME_M5
ZONE_LOOKBACK = 500
SL_BUFFER = 75000 
TP_RATIO = 1.2
MAGIC = 77775
CHECK_RANGE = 100000 
FAST_ZONE_STRENGTH_THRESHOLD = 40
ZONE_STRENGTH_THRESHOLD = int(os.getenv("ZONE_STRENGTH_THRESHOLD", "30"))
ATR_THRESHOLD_FACTOR = float(os.getenv("ATR_THRESHOLD_FACTOR", "0.8"))

# Pattern trading configuration
PATTERN_SCALP_ENABLED = os.getenv("PATTERN_SCALP_ENABLED", "True").lower() == "true"
PATTERN_COOLDOWN = int(os.getenv("PATTERN_COOLDOWN", "60"))  # 2 minutes
MIN_PATTERN_STRENGTH = 60

AUTO_SWITCH_ENABLED = os.getenv("AUTO_SWITCH_ENABLED", "False").lower() == "true"
MANUAL_OVERRIDE = os.getenv("MANUAL_OVERRIDE", "False").lower() == "true"
ALLOWED_HOURS = [(8, 10), (15, 17), (20, 0)]

# --- State
active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_zone_alert_time = None
_last_switch_time = None
_last_status = None
_current_mode = None
_last_pattern_trade_time = None
_last_pattern_scan_time = None
_last_manual_override_alert = None
_last_zone_summary = None
_last_price_update = None
PRICE_UPDATE_THRESHOLD = 500  # Only send price updates if price changes by this much

def init_globals():
    global active_trades, zone_touch_counts, _last_demand_zones, _last_supply_zones
    global _last_zone_alert_time, _last_switch_time, _last_status, _current_mode
    global _last_pattern_trade_time, _last_pattern_scan_time, _last_zone_scan
    global _last_price_update
    
    active_trades = {}
    zone_touch_counts = {}
    _last_demand_zones = []
    _last_supply_zones = []
    _last_zone_alert_time = None
    _last_switch_time = None
    _last_status = None
    _current_mode = None
    _last_pattern_trade_time = None
    _last_pattern_scan_time = None
    _last_zone_scan = None
    _last_price_update = None

init_globals()

def clean_stale_trades():
    """Removes trades from active_trades if they are no longer open in MT5"""
    open_positions = mt5.positions_get(symbol=SYMBOL)
    open_sides = {p.type for p in open_positions} if open_positions else set()
    
    stale_keys = []
    for key in list(active_trades.keys()):
        side = key[0]  # "buy" or "sell"
        mt5_side = 0 if side == "buy" else 1
        if mt5_side not in open_sides:
            stale_keys.append(key)

    for k in stale_keys:
        del active_trades[k]
        send_telegram_message(f"🧹 Cleaned ghost trade: {k[0].upper()} position removed from memory", priority="low")

def send_zone_summary(demand_stats, supply_stats):
    global _last_zone_summary
    current_summary = (demand_stats['accepted'], demand_stats['rejected'], 
                       supply_stats['accepted'], supply_stats['rejected'], 
                       max(demand_stats['max'], supply_stats['max']))
    
    if current_summary == _last_zone_summary:
        return  # No change, skip
    _last_zone_summary = current_summary
    
    summary = (
        f"📊 Zone Scan Summary:\n"
        f"🟢 Demand Zones → Found: {demand_stats['accepted']} | Rejected: {demand_stats['rejected']}\n"
        f"🔴 Supply Zones → Found: {supply_stats['accepted']} | Rejected: {supply_stats['rejected']}\n"
        f"🏆 Max Strength: {max(demand_stats['max'], supply_stats['max']):.0f}%"
    )
    send_telegram_message(summary, priority="normal")

def get_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    if rates is None or len(rates) == 0:
        print(f"[❌ ERROR] Failed to retrieve data for {symbol} on {timeframe}")
        return pd.DataFrame()
    
    df = pd.DataFrame(rates)
    if 'time' not in df.columns:
        print(f"[❌ ERROR] No time column in data for {symbol}")
        return pd.DataFrame()
    
    try:
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df['timestamp'] = df['time']
    except Exception as e:
        print(f"[❌ ERROR] Time conversion failed: {str(e)}")
        return pd.DataFrame()
    
    return df

def is_within_trading_hours():
    now = datetime.now()
    current_hour = now.hour
    for start, end in ALLOWED_HOURS:
        if start < end:
            if start <= current_hour < end:
                return True
        else:
            if current_hour >= start or current_hour < end:
                return True
    return False

def notify_strategy_change(mode):
    global _current_mode
    if mode != _current_mode:
        _current_mode = mode
        msg = (
            "📢 Mode Change: Trend-Follow (Safe)\n✅ Focused on strong zones only. Slower but higher quality signals."
            if mode == "trend_follow"
            else "⚡ Mode Change: Aggressive Scalper (Beast)\n🔥 Bot will now react faster to momentum zones and candlestick patterns."
        )
        send_telegram_message(msg, priority="high")

def calculate_trend(df):
    df['SMA50'] = df['close'].rolling(50).mean()
    df['ATR14'] = df['high'].rolling(14).max() - df['low'].rolling(14).min()
    if len(df) < 51:
        return None, None
    last = df['close'].iloc[-1]
    sma = df['SMA50'].iloc[-1]
    atr = df['ATR14'].iloc[-1]
    if last > sma:
        return "uptrend", atr
    elif last < sma:
        return "downtrend", atr
    return "sideways", atr

def determine_combined_trend():
    h1_df = get_data(SYMBOL, mt5.TIMEFRAME_H1, 150)
    h4_df = get_data(SYMBOL, mt5.TIMEFRAME_H4, 150)
    h1_trend, h1_atr = calculate_trend(h1_df)
    h4_trend, _ = calculate_trend(h4_df)
    dynamic_threshold = h1_df['ATR14'].rolling(20).mean().iloc[-1] if 'ATR14' in h1_df else 200
    adjusted_threshold = ATR_THRESHOLD_FACTOR * dynamic_threshold
    trend = h1_trend if h1_trend == h4_trend and h1_trend != "sideways" else "sideways"
    return trend, h1_atr, adjusted_threshold

def zones_equal(z1, z2):
    return len(z1) == len(z2) and all(
        abs(a['price'] - b['price']) < 1e-5 and a['time'] == b['time'] for a, b in zip(z1, z2)
    )

def should_switch_mode(current_time):
    global _last_switch_time
    cooldown = 1800  # 30 minutes
    if _last_switch_time is None or (current_time - _last_switch_time).total_seconds() > cooldown:
        _last_switch_time = current_time
        return True
    return False

def scan_for_patterns(symbol, timeframe, bars=5):
    """Enhanced pattern scanning using multiple timeframes"""
    df = get_data(symbol, timeframe, bars)
    if len(df) < 2:
        return None
    
    patterns = detect_patterns(df)
    
    if patterns:
        candle = df.iloc[-1]
        return {
            'patterns': patterns,
            'candle': candle,
            'prev_candle': df.iloc[-2],
            'time': df['time'].iloc[-1]
        }
    return None

def execute_pattern_trade(pattern_data, strategy_mode, trend):
    """Execute trades based on detected patterns"""
    global _last_pattern_trade_time, active_trades
    
    patterns = pattern_data['patterns']
    candle = pattern_data['candle']
    prev_candle = pattern_data['prev_candle']
    point = mt5.symbol_info(SYMBOL).point
    tick = mt5.symbol_info_tick(SYMBOL)
    
    if not tick:
        return False
    
    # Get symbol info for spread
    symbol_info = mt5.symbol_info(SYMBOL)
    spread = symbol_info.spread * point if symbol_info else 0
    
    bullish_patterns = ['bullish_pin_bar', 'hammer', 'bullish_engulfing', 'bullish_marubozu', 'hammer_bullish']
    bearish_patterns = ['bearish_pin_bar', 'shooting_star', 'bearish_engulfing', 'bearish_marubozu', 'shooting_star_bearish']
    
    entry_price = tick.ask if any(p in patterns for p in bullish_patterns) else tick.bid
    
    # Calculate buffer based on spread
    buffer = max(SL_BUFFER * point, spread * 2)
    
    if any(p in patterns for p in bullish_patterns):
        sl = candle.low - buffer
        tp = entry_price + (entry_price - sl) * TP_RATIO
        side = "buy"
    elif any(p in patterns for p in bearish_patterns):
        sl = candle.high + buffer
        tp = entry_price - (sl - entry_price) * TP_RATIO
        side = "sell"
    else:
        return False
    
    if active_trades.get(side):
        send_telegram_message(f"⏳ Skipping {side.upper()} pattern trade - active trade exists", priority="low")
        return False
    
    if (trend == "uptrend" and side == "sell") or (trend == "downtrend" and side == "buy"):
        send_telegram_message(f"⛔ Pattern trade blocked due to trend conflict ({trend})", priority="low")
        return False
    
    lot_size = 0.001
    result = place_order(SYMBOL, side, lot_size, sl, tp, MAGIC)
    
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        _last_pattern_trade_time = datetime.now()
        active_trades[(side, 'pattern')] = {
            "entry": entry_price,
            "sl": sl,
            "tp": tp,
            "zone_type": "pattern",
            "strategy_mode": strategy_mode,
            "entry_time": datetime.now(),
            "patterns": patterns
        }
        send_telegram_message(
            f"⚡ PATTERN TRADE ({', '.join(patterns)})\n"
            f"Direction: {side.upper()} | Entry: {entry_price:.2f}\n"
            f"SL: {sl:.2f} | TP: {tp:.2f} | Spread: {spread/point:.0f}pts",
            priority="high"
        )
        return True
    else:
        error_msg = getattr(result, 'retcode', 'N/A')
        if hasattr(result, 'retcode'):
            error_msg = f"{result.retcode} - {mt5.return_string(result.retcode)}"
        send_telegram_message(f"❌ Pattern trade failed. Error: {error_msg}", priority="high")
        return False

def should_update_price(current_price):
    global _last_price_update
    if _last_price_update is None:
        _last_price_update = current_price
        return True
    if abs(current_price - _last_price_update) >= PRICE_UPDATE_THRESHOLD:
        _last_price_update = current_price
        return True
    return False

def monitor_and_trade(strategy_mode="trend_follow", fixed_lot=None):
    global _last_zone_scan, _last_demand_zones, _last_supply_zones
    global _last_manual_override_alert, _last_pattern_trade_time
    global _last_zone_alert_time, _last_status, _last_pattern_scan_time
    global _last_price_update
    
    now = datetime.now()
    clean_stale_trades()
    
    # Refresh zones every 5 minutes
    if _last_zone_scan is None or (now - _last_zone_scan).total_seconds() > ZONE_REFRESH_INTERVAL:
        demand_zones, supply_zones = scan_zones(get_data, SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
        if not demand_zones and not supply_zones:
            print("[⚠️ WARNING] Zone scanning returned empty results")
        _last_zone_scan = now
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones
    
    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if m1_df.empty or 'time' not in m1_df.columns:
        print("[❌ ERROR] Failed to get valid M1 data")
        return

    if strategy_mode == "trend_follow" and not is_within_trading_hours():
        if _last_status != "sleep":
            send_telegram_message(
                "🛌 Trend-Follow sleeping. ⏰ Best hours: 08–10, 15–17, 20–00\n"
                "⚡ Aggressive Scalper is still active 24/7 for momentum trades.",
                priority="normal"
            )
            _last_status = "sleep"
        return
    elif _last_status != "awake":
        send_telegram_message("🔔 Bot Active: Monitoring zones and patterns for trade setups. 📊", priority="normal")
        _last_status = "awake"

    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        return

    demand_raw, demand_stats = detect_zones(h1_df, zone_type='demand')
    supply_raw, supply_stats = detect_zones(h1_df, zone_type='supply')

    all_demand_zones = []
    all_supply_zones = []

    for z in demand_raw:
        price = (z['zone_low'] + z['zone_high']) / 2
        formatted = {
            'price': price,
            'type': "strict_demand",
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        }
        all_demand_zones.append(formatted)

    for z in supply_raw:
        price = (z['zone_low'] + z['zone_high']) / 2
        formatted = {
            'price': price,
            'type': "strict_supply",
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        }
        all_supply_zones.append(formatted)

    send_zone_summary(demand_stats, supply_stats)

    if strategy_mode == "aggressive":
        demand_zones = [z for z in all_demand_zones if z['strength'] >= FAST_ZONE_STRENGTH_THRESHOLD][:3]
        supply_zones = [z for z in all_supply_zones if z['strength'] >= FAST_ZONE_STRENGTH_THRESHOLD][:3]
    else:
        demand_zones = all_demand_zones[:2]
        supply_zones = all_supply_zones[:2]

    current_h1_time = h1_df['time'].iloc[-1]
    if (not zones_equal(demand_zones, _last_demand_zones) or not zones_equal(supply_zones, _last_supply_zones)) and _last_zone_alert_time != current_h1_time:
        _last_zone_alert_time = current_h1_time
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones

        msg = ["📈 Zone Update: Fresh Levels Detected"]
        msg.append("\n🟢 Demand Zones:")
        msg.extend([
            f"• {z['price']:.2f} | Strength: {z['strength']}% | Type: {z['type']} | ⏰ {z['time'].strftime('%H:%M')}"
            for z in demand_zones
        ] or ["⚠️ No demand zones found."])
        msg.append("\n\n🔴 Supply Zones:")
        msg.extend([
            f"• {z['price']:.2f} | Strength: {z['strength']}% | Type: {z['type']} | ⏰ {z['time'].strftime('%H:%M')}"
            for z in supply_zones
        ] or ["⚠️ No supply zones found."])
        send_telegram_message("\n".join(msg), priority="normal")

    trend = get_trend(SYMBOL)
    atr = 100000
    atr_threshold = 100000
    dynamic_range = max(CHECK_RANGE, int(atr * 4)) if atr else CHECK_RANGE

    if MANUAL_OVERRIDE:
        strategy_mode = _current_mode or "trend_follow"
    if _last_manual_override_alert != strategy_mode:
        send_telegram_message(f"📌 Manual override active: {strategy_mode}", priority="normal")
        _last_manual_override_alert = strategy_mode
    elif AUTO_SWITCH_ENABLED and should_switch_mode(now):
        if atr and atr < atr_threshold * 0.95 and _current_mode != "aggressive":
            strategy_mode = "aggressive"
            notify_strategy_change(strategy_mode)
        elif atr and atr > atr_threshold * 1.05 and _current_mode != "trend_follow":
            strategy_mode = "trend_follow"
            notify_strategy_change(strategy_mode)
        else:
            strategy_mode = _current_mode or "trend_follow"
    else:
        strategy_mode = _current_mode or "trend_follow"

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if len(m1_df) < 4:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return

    price = tick.bid
    point = mt5.symbol_info(SYMBOL).point
    
    if should_update_price(price):
        send_telegram_message(f"📉 Current VIX75 Price: {price:.2f} | Mode: {strategy_mode.upper()}", priority="low")

    if not demand_zones and not supply_zones and abs(price - h1_df['close'].iloc[-1]) > CHECK_RANGE:
        zone_type = 'demand' if trend == 'uptrend' else 'supply' if trend == 'downtrend' else 'demand'
        emergency_zone = {
            'price': price,
            'type': f"emergency_{zone_type}",
            'time': datetime.now(),
            'strength': 85,
            'zone_low': price - 500 if zone_type == 'demand' else price - 250,
            'zone_high': price + 250 if zone_type == 'demand' else price + 500
        }

        if zone_type == 'demand':
            demand_zones.append(emergency_zone)
        else:
            supply_zones.append(emergency_zone)

        send_telegram_message(f"🚨 Emergency {zone_type.upper()} zone injected near price {price:.2f} due to drift", priority="high")

    if strategy_mode == "aggressive" and PATTERN_SCALP_ENABLED:
        if _last_pattern_scan_time is None or (now - _last_pattern_scan_time).total_seconds() >= 30:
            _last_pattern_scan_time = now
            
            pattern_data = scan_for_patterns(SYMBOL, TIMEFRAME_PATTERN)
            
            if pattern_data:
                send_telegram_message(f"🔍 Detected patterns: {', '.join(pattern_data['patterns'])}", priority="low")
                
                if (_last_pattern_trade_time is None or 
                    (now - _last_pattern_trade_time).total_seconds() > PATTERN_COOLDOWN):
                    
                    if trend != "sideways":
                        execute_pattern_trade(pattern_data, strategy_mode, trend)

    last3_candles = m1_df.iloc[-4:-1]
    breaker_block = detect_breaker_block(last3_candles)
    
    signals = trade_decision_engine(
        symbol=SYMBOL,
        point=point,
        current_price=price,
        trend=trend,
        demand_zones=demand_zones,
        supply_zones=supply_zones,
        last3_candles=m1_df.iloc[-4:-1],
        active_trades=active_trades,
        zone_touch_counts=zone_touch_counts,
        SL_BUFFER=SL_BUFFER,
        TP_RATIO=TP_RATIO,
        CHECK_RANGE=dynamic_range,
        LOT_SIZE=fixed_lot or 0.001,
        MAGIC=MAGIC,
        strategy_mode=strategy_mode,
        breaker_block=breaker_block
    )

    for signal in signals:
        result = place_order(SYMBOL, signal['side'], signal['lot'], signal['sl'], signal['tp'], MAGIC, atr=atr)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            send_telegram_message(
                f"✅ ORDER PLACED: {signal['side'].upper()} {SYMBOL}\n"
                f"Entry: {signal['entry']:.2f} | SL: {signal['sl']:.2f} | TP: {signal['tp']:.2f}",
                priority="high"
            )
            active_trades[(signal['side'], signal['zone'])] = {
                "entry": signal['entry'],
                "sl": signal['sl'],
                "tp": signal['tp'],
                "zone_type": signal.get('zone_type', ''),
                "strategy_mode": signal.get('strategy', strategy_mode),
                "entry_time": datetime.now()
            }
        else:
            send_telegram_message(f"❌ Order Failed. Retcode: {getattr(result, 'retcode', 'N/A')}", priority="high")
    
    if not signals and strategy_mode != "aggressive":
        pattern_df = m1_df.iloc[-3:]
        detected_patterns = detect_patterns(pattern_df)

        if trend == "sideways":
            send_telegram_message("🔕 Skipped pattern scalp — sideways trend", priority="low")
        elif _last_pattern_trade_time and (now - _last_pattern_trade_time).total_seconds() < 300:
            send_telegram_message("🕒 Skipped pattern scalp — last pattern trade was under 5 mins ago", priority="low")
        elif detected_patterns:
            side = None
            candle = m1_df.iloc[-1]
            prev_candle = m1_df.iloc[-2]
            entry = candle.close
            point = mt5.symbol_info(SYMBOL).point

            if any(p in detected_patterns for p in ["bullish_pin_bar", "bullish_engulfing", "hammer_bullish"]):
                side = "buy"
                sl = candle.low - SL_BUFFER * point
                tp = entry + TP_RATIO * (entry - sl)
            elif any(p in detected_patterns for p in ["bearish_pin_bar", "bearish_engulfing", "shooting_star_bearish"]):
                side = "sell"
                sl = candle.high + SL_BUFFER * point
                tp = entry - TP_RATIO * (sl - entry)

            if side and not active_trades.get(side):
                send_telegram_message(f"🧠 Enhanced Pattern Detected: {', '.join(detected_patterns)}", priority="normal")
                result = place_order(SYMBOL, side, fixed_lot or 0.001, sl, tp, MAGIC, atr=atr)
                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    _last_pattern_trade_time = datetime.now()
                    active_trades[(side, 'pattern')] = {
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "zone_type": "pattern",
                        "strategy_mode": "pattern",
                        "entry_time": datetime.now(),
                        "patterns": detected_patterns
                    }
                    send_telegram_message(f"✅ PATTERN ORDER PLACED: {side.upper()} | SL: {sl:.2f} | TP: {tp:.2f}", priority="high")
                else:
                    send_telegram_message(f"❌ Pattern scalp order failed. Retcode: {getattr(result, 'retcode', 'N/A')}", priority="high")
        else:
            send_telegram_message("📭 No valid reversal patterns found for scalp entry.", priority="low")

    trail_sl(SYMBOL, MAGIC)
    flush_message_queue()  # Ensure all queued messages are sent