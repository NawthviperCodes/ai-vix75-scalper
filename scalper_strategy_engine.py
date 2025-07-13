# === scalper_strategy_engine.py (Fixed Emojis + No Telegram Spam on Sleep) ===
import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, trail_sl
from performance_tracker import log_trade
import pytz
import os
from dotenv import load_dotenv

load_dotenv()

AUTO_SWITCH_ENABLED = os.getenv("AUTO_SWITCH_ENABLED", "False").lower() == "true"
MANUAL_OVERRIDE = os.getenv("MANUAL_OVERRIDE", "False").lower() == "true"
ATR_THRESHOLD_FACTOR = float(os.getenv("ATR_THRESHOLD_FACTOR", "0.8"))
ZONE_STRENGTH_THRESHOLD = int(os.getenv("ZONE_STRENGTH_THRESHOLD", "50"))
FAST_CONFIRMATION_ENABLED = os.getenv("FAST_CONFIRMATION_ENABLED", "False").lower() == "true"

SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
ZONE_LOOKBACK = 150
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 30000

ALLOWED_HOURS = [(9, 10), (12, 13), (16, 17), (20, 22)]

active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None
_current_mode = None
_last_switch_time = None
_last_status = None  # 👈 Track bot sleep/awake state


def is_within_trading_hours():
    now = datetime.now()
    current_hour = now.hour
    for start, end in ALLOWED_HOURS:
        if start <= current_hour < end:
            return True
    return False


def notify_strategy_change(mode):
    global _current_mode
    if mode == _current_mode:
        return
    _current_mode = mode
    msg = (
        "📢 Switched to Trend-Follow mode (Safe).\n✅ Using only strong strict zones."
        if mode == "trend_follow"
        else "⚡️ Switched to Aggressive Scalper mode (Beast).\n🔥 Hyper-reactive to fast zones + weak strict zones."
    )
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
    else:
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
    if len(z1) != len(z2):
        return False
    for a, b in zip(z1, z2):
        if abs(a['price'] - b['price']) > 1e-5 or a['time'] != b['time']:
            return False
    return True


def send_zone_alerts(demand_zones, supply_zones, fast_demand, fast_supply, strength_threshold=50, all_demand_zones=None, all_supply_zones=None):
    msg = "📈 New Zones Detected:\n"

    # Strict Demand Zones (strong)
    msg += "\n🟢 Strict Demand Zones:\n"
    if demand_zones:
        msg += "\n".join([
            f"- {z['price']:.2f} ({z['strength']}%) @ {z['time'].strftime('%H:%M')}" for z in demand_zones
        ])
    else:
        msg += f"None found. ⚠️ Reason: All detected demand zones had strength below {strength_threshold}%."

    # Strict Supply Zones (strong)
    msg += "\n\n🔴 Strict Supply Zones:\n"
    if supply_zones:
        msg += "\n".join([
            f"- {z['price']:.2f} ({z['strength']}%) @ {z['time'].strftime('%H:%M')}" for z in supply_zones
        ])
    else:
        msg += f"None found. ⚠️ Reason: All detected supply zones had strength below {strength_threshold}%."

    # 🔸 Weak Demand Zones
    if all_demand_zones is not None:
        weak_demand = [z for z in all_demand_zones if z['strength'] < strength_threshold]
        if weak_demand:
            msg += "\n\n🔸 Weak Demand Zones (filtered out):\n"
            msg += "\n".join([
                f"- {z['price']:.2f} ({z['strength']}%) @ {z['time'].strftime('%H:%M')}" for z in weak_demand
            ])

    # 🔹 Weak Supply Zones
    if all_supply_zones is not None:
        weak_supply = [z for z in all_supply_zones if z['strength'] < strength_threshold]
        if weak_supply:
            msg += "\n\n🔹 Weak Supply Zones (filtered out):\n"
            msg += "\n".join([
                f"- {z['price']:.2f} ({z['strength']}%) @ {z['time'].strftime('%H:%M')}" for z in weak_supply
            ])

    # ⚡ Fast Zones
    if fast_demand:
        msg += "\n\n⚡ Fast Demand Zones:\n" + "\n".join([
            f"- {z['price']:.2f} (🔥) @ {z['time'].strftime('%H:%M')}" for z in fast_demand
        ])
    if fast_supply:
        msg += "\n\n⚡ Fast Supply Zones:\n" + "\n".join([
            f"- {z['price']:.2f} (🔥) @ {z['time'].strftime('%H:%M')}" for z in fast_supply
        ])

    send_telegram_message(msg)





def should_switch_mode(current_time):
    global _last_switch_time
    cooldown_seconds = 1800
    if _last_switch_time is None or (current_time - _last_switch_time).total_seconds() > cooldown_seconds:
        _last_switch_time = current_time
        return True
    return False


def check_for_closed_trades():
    start_of_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start_of_today, datetime.now())
    if not deals:
        print("[INFO] No deals found in history.")
        return

    seen_positions = set()

    # Group deals by position_id for clearer matching
    deals_by_position = {}
    for deal in deals:
        deals_by_position.setdefault(deal.position_id, []).append(deal)

    for position_id, position_deals in deals_by_position.items():
        # Find entry deal (entry == 1)
        entry_deal = next((d for d in position_deals if d.entry == 1), None)
        if not entry_deal:
            continue  # No entry deal for this position

        # Find exit deal(s) (entry == 0) that correspond to this position
        exit_deals = [d for d in position_deals if d.entry == 0]
        if not exit_deals:
            continue  # Still open or no exit recorded

        for exit_deal in exit_deals:
            # Avoid logging same exit twice
            unique_key = (position_id, exit_deal.time)
            if unique_key in seen_positions:
                continue

            # Correct entry and exit time ordering
            time_1 = datetime.fromtimestamp(entry_deal.time, tz=pytz.utc).astimezone()
            time_2 = datetime.fromtimestamp(exit_deal.time, tz=pytz.utc).astimezone()

            entry_time = min(time_1, time_2)
            exit_time = max(time_1, time_2)

            # Determine side based on price movement
            if exit_deal.price > entry_deal.price:
                side = "buy"
            else:
                side = "sell"

            lot_size = exit_deal.volume
            contract_size = mt5.symbol_info(SYMBOL).trade_contract_size
            price_diff = exit_deal.price - entry_deal.price
            direction = 1 if side == "buy" else -1
            profit = price_diff * direction * lot_size * contract_size

            print(f"[DEBUG] Logging closed trade | Side: {side} | Entry: {entry_deal.price} | Exit: {exit_deal.price} | Profit: {profit:.2f}")

            log_trade(
                entry_time,
                exit_time,
                side,
                entry_deal.price,
                exit_deal.price,
                profit,
                "win" if profit > 0 else "loss",
                _current_mode or "unknown",
                None,
                None
            )
            seen_positions.add(unique_key)

            # Remove trade from active_trades if present
            to_delete = None
            for key in active_trades.keys():
                if key[0] == side and abs(key[1] - entry_deal.price) < CHECK_RANGE * mt5.symbol_info(SYMBOL).point:
                    to_delete = key
                    break
            if to_delete:
                del active_trades[to_delete]
                print(f"[INFO] Removed {side.upper()} trade from active_trades: {to_delete}")
            else:
                print(f"[WARN] Orphan closed trade: {side.upper()} at {entry_deal.price} (not in active_trades)")




def monitor_and_trade(strategy_mode="trend_follow", fixed_lot=None):
    global _last_demand_zones, _last_supply_zones, _last_fast_demand, _last_fast_supply, _last_zone_alert_time, _last_status

    now = datetime.now()
    within_hours = is_within_trading_hours()

    if within_hours:
        if _last_status != "awake":
            send_telegram_message("🔔 Bot is awake! Let's make money! 🤑\n🕒 Optimal trading hours started.")
            _last_status = "awake"
        else:
            print("[INFO] Bot is already active during trading hours.")
    else:
        if _last_status != "sleep":
            send_telegram_message("😴 Bot is currently sleeping. Outside optimal trading hours.\n⏰ Best hours: 09:00–10:00, 12:00–13:00, 16:00–17:00, 20:00–22:00 (SA Time)")
            _last_status = "sleep"
        return

    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        print("[ERROR] No H1 data.")
        return

    demand_zones, supply_zones = detect_zones(h1_df)
    all_demand_zones, all_supply_zones = demand_zones.copy(), supply_zones.copy()

    fast_demand, fast_supply = detect_fast_zones(h1_df)

    if strategy_mode == "trend_follow":
        demand_zones = [z for z in demand_zones if z['strength'] >= ZONE_STRENGTH_THRESHOLD]
        supply_zones = [z for z in supply_zones if z['strength'] >= ZONE_STRENGTH_THRESHOLD]

    current_h1_time = h1_df['time'].iloc[-1]
    if ((not zones_equal(demand_zones, _last_demand_zones) or
         not zones_equal(supply_zones, _last_supply_zones) or
         not zones_equal(fast_demand, _last_fast_demand) or
         not zones_equal(fast_supply, _last_fast_supply)) and
            _last_zone_alert_time != current_h1_time):
        _last_zone_alert_time = current_h1_time
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones
        _last_fast_demand = fast_demand
        _last_fast_supply = fast_supply
        send_zone_alerts(
    demand_zones,
    supply_zones,
    fast_demand,
    fast_supply,
    strength_threshold=ZONE_STRENGTH_THRESHOLD,
    all_demand_zones=all_demand_zones,
    all_supply_zones=all_supply_zones
)


    trend, atr, atr_threshold = determine_combined_trend()

    if MANUAL_OVERRIDE:
        send_telegram_message(f"📌 Manual override active. Locked to: {strategy_mode}")
        notify_strategy_change(strategy_mode)
    elif AUTO_SWITCH_ENABLED and should_switch_mode(now):
        if atr and atr < atr_threshold * 0.95:
            strategy_mode = "aggressive"
        elif atr and atr > atr_threshold * 1.05:
            strategy_mode = "trend_follow"
        notify_strategy_change(strategy_mode)
    else:
        notify_strategy_change(strategy_mode)

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if len(m1_df) < 4:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
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
        side = signal['side']
        entry = signal['entry']
        sl = signal['sl']
        tp = signal['tp']
        zone = signal['zone']
        lot = signal['lot']

        side_emoji = "🟢" if side == "buy" else "🔴"
        send_telegram_message(
            f"{side_emoji} {side.upper()} SIGNAL\n"
            f"Zone: {zone:.2f} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot:.3f}"
        )

        result = place_order(SYMBOL, side, lot, sl, tp, MAGIC)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            send_telegram_message(
                f"✅ ORDER PLACED: {side.upper()} {SYMBOL}\nPrice: {result.price:.2f} | SL: {sl:.2f} | TP: {tp:.2f}"
            )
            active_trades[(side, zone)] = True
        else:
            send_telegram_message(
                f"❌ Order Failed. Retcode: {getattr(result, 'retcode', 'N/A')}"
            )

    trail_sl(SYMBOL, MAGIC)
    check_for_closed_trades()
