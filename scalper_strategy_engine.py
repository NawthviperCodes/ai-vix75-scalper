# === scalper_strategy_engine.py (Elite VIX75 Zone Trader + ATR Adaptive Mode) ===

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, trail_sl
from performance_tracker import log_trade
import os
from dotenv import load_dotenv

load_dotenv()

# --- Configuration
SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
ZONE_LOOKBACK = 150
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 30000
FAST_ZONE_STRENGTH_THRESHOLD = 50
ZONE_STRENGTH_THRESHOLD = int(os.getenv("ZONE_STRENGTH_THRESHOLD", "30"))
ATR_THRESHOLD_FACTOR = float(os.getenv("ATR_THRESHOLD_FACTOR", "0.8"))

AUTO_SWITCH_ENABLED = os.getenv("AUTO_SWITCH_ENABLED", "False").lower() == "true"
MANUAL_OVERRIDE = os.getenv("MANUAL_OVERRIDE", "False").lower() == "true"
ALLOWED_HOURS = [
    (8, 10),    # Early setups
    (15, 17),   # Momentum phase
    (20, 0)     # Evening volatility surge
]

# --- State
active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None
_current_mode = None
_last_switch_time = None
_last_status = None


def is_within_trading_hours():
    now = datetime.now()
    return any(start <= now.hour < end for start, end in ALLOWED_HOURS)


def notify_strategy_change(mode):
    global _current_mode
    if mode != _current_mode:
        _current_mode = mode
        msg = (
    "📢 Mode Change: Trend-Follow (Safe)\n✅ Focused on strong zones only. Slower but higher quality signals."
    if mode == "trend_follow"
    else "⚡ Mode Change: Aggressive Scalper (Beast)\n🔥 Bot will now react faster to momentum zones. Expect quicker signals.")
        send_telegram_message(msg)


def get_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


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


def send_zone_alerts(demand_zones, supply_zones, fast_demand, fast_supply):
    msg = "📈 Zone Update: Fresh Levels Detected\n"

    msg += "\n🟢 Demand Zones (Strong Buys):\n"
    msg += "\n".join([
        f"• {z['price']:.2f} | Strength: {z['strength']}% | ⏰ {z['time'].strftime('%H:%M')}" for z in demand_zones
    ]) or f"⚠️ No strong demand zones found (below {ZONE_STRENGTH_THRESHOLD}%)."

    msg += "\n\n🔴 Supply Zones (Strong Sells):\n"
    msg += "\n".join([
        f"• {z['price']:.2f} | Strength: {z['strength']}% | ⏰ {z['time'].strftime('%H:%M')}" for z in supply_zones
    ]) or f"⚠️ No strong supply zones found (below {ZONE_STRENGTH_THRESHOLD}%)."

    if fast_demand:
        msg += "\n\n⚡ Fast Demand Zones (Quick Reaction):\n" + "\n".join([
            f"• {z['price']:.2f} | Strength: {z['strength']}% | ⏰ {z['time'].strftime('%H:%M')}" for z in fast_demand
        ])
    if fast_supply:
        msg += "\n\n⚡ Fast Supply Zones (Quick Reaction):\n" + "\n".join([
            f"• {z['price']:.2f} | Strength: {z['strength']}% | ⏰ {z['time'].strftime('%H:%M')}" for z in fast_supply
        ])


    send_telegram_message(msg)


def should_switch_mode(current_time):
    global _last_switch_time
    cooldown = 1800
    if _last_switch_time is None or (current_time - _last_switch_time).total_seconds() > cooldown:
        _last_switch_time = current_time
        return True
    return False


def monitor_and_trade(strategy_mode="trend_follow", fixed_lot=None):
    global _last_demand_zones, _last_supply_zones, _last_fast_demand, _last_fast_supply, _last_zone_alert_time, _last_status

    now = datetime.now()
    
    if strategy_mode == "trend_follow" and not is_within_trading_hours():
        
        if _last_status != "sleep":
            send_telegram_message(
            "😴 Trend-Follow sleeping. ⏰ Best hours: 08–10, 15–17, 20–00\n"
            "⚡ Aggressive Scalper is still active 24/7 for momentum trades."
        )
        _last_status = "sleep"
        return
   
    elif _last_status != "awake":
          send_telegram_message("🔔 Bot Active: Monitoring zones for trade setups. 📊")
          _last_status = "awake"
        

    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        return

    demand_zones, supply_zones = detect_zones(h1_df)
    fast_demand, fast_supply = detect_fast_zones(h1_df)
    fast_demand = [z for z in fast_demand if z['strength'] >= FAST_ZONE_STRENGTH_THRESHOLD]
    fast_supply = [z for z in fast_supply if z['strength'] >= FAST_ZONE_STRENGTH_THRESHOLD]

    current_h1_time = h1_df['time'].iloc[-1]
    if (
        (not zones_equal(demand_zones, _last_demand_zones) or
         not zones_equal(supply_zones, _last_supply_zones) or
         not zones_equal(fast_demand, _last_fast_demand) or
         not zones_equal(fast_supply, _last_fast_supply)) and
        _last_zone_alert_time != current_h1_time
    ):
        _last_zone_alert_time = current_h1_time
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones
        _last_fast_demand = fast_demand
        _last_fast_supply = fast_supply
        send_zone_alerts(demand_zones, supply_zones, fast_demand, fast_supply)

    trend, atr, atr_threshold = determine_combined_trend()

    if MANUAL_OVERRIDE:
        send_telegram_message(f"📌 Manual override active: {strategy_mode}")
    elif AUTO_SWITCH_ENABLED and should_switch_mode(now):
        if atr and atr < atr_threshold * 0.95:
            strategy_mode = "aggressive"
        elif atr and atr > atr_threshold * 1.05:
            strategy_mode = "trend_follow"
    notify_strategy_change(strategy_mode)

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if len(m1_df) < 4:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return

    price = tick.bid
    point = mt5.symbol_info(SYMBOL).point

    signals = trade_decision_engine(
        symbol=SYMBOL,
        point=point,
        current_price=price,
        trend=trend,
        demand_zones=demand_zones + fast_demand,
        supply_zones=supply_zones + fast_supply,
        last3_candles=m1_df.iloc[-4:-1],
        active_trades=active_trades,
        zone_touch_counts=zone_touch_counts,
        SL_BUFFER=SL_BUFFER,
        TP_RATIO=TP_RATIO,
        CHECK_RANGE=CHECK_RANGE,
        LOT_SIZE=fixed_lot or 0.001,
        MAGIC=MAGIC,
        strategy_mode=strategy_mode,
    )

    for signal in signals:
        result = place_order(SYMBOL, signal['side'], signal['lot'], signal['sl'], signal['tp'], MAGIC, atr=atr)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            send_telegram_message(
                f"✅ ORDER PLACED: {signal['side'].upper()} {SYMBOL}\n"
                f"Entry: {signal['entry']:.2f} | SL: {signal['sl']:.2f} | TP: {signal['tp']:.2f}"
            )
            active_trades[(signal['side'], signal['zone'])] = {
                "entry": signal['entry'],
                "sl": signal['sl'],
                "tp": signal['tp'],
                "zone_type": signal['zone_type'],
                "strategy_mode": signal['strategy'],
                "entry_time": datetime.now()
            }
        else:
            send_telegram_message(f"❌ Order Failed. Retcode: {getattr(result, 'retcode', 'N/A')}")

    trail_sl(SYMBOL, MAGIC)
