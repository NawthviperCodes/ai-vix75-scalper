import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, trail_sl
from performance_tracker import log_trade
import pytz
from dotenv import load_dotenv
import os

load_dotenv()
AUTO_SWITCH_ENABLED = os.getenv("AUTO_SWITCH_ENABLED", "False").lower() == "true"
MANUAL_OVERRIDE = os.getenv("MANUAL_OVERRIDE", "False").lower() == "true"
ATR_THRESHOLD_FACTOR = float(os.getenv("ATR_THRESHOLD_FACTOR", "0.8"))

SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
ZONE_LOOKBACK = 100
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 30000

active_trades = {}
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None
_current_mode = None
_last_switch_time = None

def notify_strategy_change(mode):
    global _current_mode
    if mode == _current_mode:
        return  # Avoid duplicate alerts
    _current_mode = mode
    if mode == "trend_follow":
        send_telegram_message(
            "📢 Switched to Trend-Follow mode (Safe).\n"
            "✅ This strategy waits for price to align with the overall trend and confirms with strict supply/demand zones. Designed for trending markets."
        )
    elif mode == "aggressive":
        send_telegram_message(
            "📢 Switched to Aggressive mode (Scalp Beast).\n"
            "⚡️ This strategy targets fast reactions in consolidating or ranging markets. It uses fast zones and wick rejections for high-risk, high-reward scalping."
        )

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
    h1_df = get_data(SYMBOL, mt5.TIMEFRAME_H1, 100)
    h4_df = get_data(SYMBOL, mt5.TIMEFRAME_H4, 100)

    h1_trend, h1_atr = calculate_trend(h1_df)
    h4_trend, _ = calculate_trend(h4_df)

    dynamic_threshold = h1_df['ATR14'].rolling(20).mean().iloc[-1] if 'ATR14' in h1_df else 200
    adjusted_threshold = ATR_THRESHOLD_FACTOR * dynamic_threshold

    if h1_trend == h4_trend and h1_trend != "sideways":
        trend = h1_trend
    else:
        trend = "sideways"

    return trend, h1_atr, adjusted_threshold

def print_detected_zones(demand_zones, supply_zones, fast_demand, fast_supply):
    print(f"[INFO] Strict Zones: {len(demand_zones)} demand, {len(supply_zones)} supply")
    for zone in demand_zones:
        print(f"  Demand zone @ {zone['price']:.2f} at {zone['time']}")
    for zone in supply_zones:
        print(f"  Supply zone @ {zone['price']:.2f} at {zone['time']}")

    print(f"[INFO] Fast Zones: {len(fast_demand)} demand, {len(fast_supply)} supply")
    for zone in fast_demand:
        print(f"  Fast Demand @ {zone['price']:.2f} at {zone['time']}")
    for zone in fast_supply:
        print(f"  Fast Supply @ {zone['price']:.2f} at {zone['time']}")

def should_switch_mode(current_time):
    global _last_switch_time
    if _last_switch_time is None:
        _last_switch_time = current_time
        return True
    if (current_time - _last_switch_time).total_seconds() > 1800:
        _last_switch_time = current_time
        return True
    return False

def check_for_closed_trades():
    deals = mt5.history_deals_get(datetime.now() - timedelta(days=1), datetime.now())
    if not deals:
        return

    seen = set()
    for deal in deals:
        if deal.entry != 1:
            continue
        for exit_deal in deals:
            if exit_deal.entry == 0 and exit_deal.position_id == deal.position_id and (deal.position_id, exit_deal.time) not in seen:
                entry_time = datetime.fromtimestamp(deal.time, tz=pytz.utc).astimezone()
                exit_time = datetime.fromtimestamp(exit_deal.time, tz=pytz.utc).astimezone()
                side = "buy" if deal.type == mt5.ORDER_TYPE_BUY else "sell"
                entry_price = deal.price
                exit_price = exit_deal.price
                profit = exit_deal.profit
                result = "win" if profit > 0 else "loss"
                positions = mt5.positions_get(position=deal.position_id)
                if positions:
                    position = positions[0]
                    sl = position.sl
                    tp = position.tp
                else:
                    sl = None
                    tp = None
                strategy_mode = _current_mode or "unknown"
                seen.add((deal.position_id, exit_deal.time))
                log_trade(entry_time, exit_time, side, entry_price, exit_price, profit, result, strategy_mode, sl, tp, silent=True)

                point = mt5.symbol_info(SYMBOL).point
                for key in list(active_trades.keys()):
                    s, z = key
                    if s == side and abs(z - entry_price) <= CHECK_RANGE * point:
                        del active_trades[key]
                        break
                break

def monitor_and_trade(strategy_mode="trend_follow", fixed_lot=None):
    global _last_demand_zones, _last_supply_zones, _last_fast_demand, _last_fast_supply, _last_zone_alert_time

    h1_df = get_data(SYMBOL, TIMEFRAME_ZONE, ZONE_LOOKBACK)
    if h1_df.empty:
        print("[ERROR] H1 unavailable.")
        return

    demand_zones, supply_zones = detect_zones(h1_df)
    fast_demand, fast_supply = detect_fast_zones(h1_df)
    print_detected_zones(demand_zones, supply_zones, fast_demand, fast_supply)

    current_h1_time = h1_df['time'].iloc[-1]
    if ((not zones_equal(demand_zones, _last_demand_zones) or not zones_equal(supply_zones, _last_supply_zones) or
         not zones_equal(fast_demand, _last_fast_demand) or not zones_equal(fast_supply, _last_fast_supply))
        and (_last_zone_alert_time != current_h1_time)):
        _last_demand_zones = demand_zones
        _last_supply_zones = supply_zones
        _last_fast_demand = fast_demand
        _last_fast_supply = fast_supply
        _last_zone_alert_time = current_h1_time
        send_telegram_message(f"📊 New zones detected.\nStrict: D={len(demand_zones)}, S={len(supply_zones)} | Fast: D={len(fast_demand)}, S={len(fast_supply)}")

    trend, atr, atr_threshold = determine_combined_trend()
    now = datetime.now()

    if MANUAL_OVERRIDE:
        send_telegram_message(f"📌 Manual override active. Locked strategy: {strategy_mode}")
        notify_strategy_change(strategy_mode)
    elif AUTO_SWITCH_ENABLED and should_switch_mode(now):
        if trend == "sideways" or (atr is not None and atr < atr_threshold):
            strategy_mode = "aggressive"
        else:
            strategy_mode = "trend_follow"
        notify_strategy_change(strategy_mode)
    else:
        notify_strategy_change(strategy_mode)

    m1_df = get_data(SYMBOL, TIMEFRAME_ENTRY, 5)
    if len(m1_df) < 4:
        print("[ERROR] Not enough M1.")
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print("[ERROR] No tick data.")
        return

    price = tick.bid
    point = mt5.symbol_info(SYMBOL).point
    print(f"[DEBUG] Fixed Lot Used: {fixed_lot}")

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
        LOT_SIZE=fixed_lot if fixed_lot else 0.001,
        MAGIC=MAGIC,
        strategy_mode=strategy_mode
    )

    for signal in signals:
        side = signal['side']
        entry = signal['entry']
        sl = signal['sl']
        tp = signal['tp']
        zone = signal['zone']
        lot = signal['lot']

        emoji = '🟢' if side == 'buy' else '🔴'
        msg = f"{emoji} {side.upper()} | Zone: {zone:.2f} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot:.3f}"
        print(msg)
        send_telegram_message(msg)

        try:
            result = place_order(SYMBOL, side, lot, sl, tp, MAGIC)
        except TypeError as e:
            print(f"[ERROR] Order placement failed: {e}")
            send_telegram_message("\u274c Order placement failed: check your trade_executor function definition")
            return

        if result is not None:
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                confirmation = (
                    f"\u2705 ORDER PLACED\n{side.upper()} {SYMBOL}\n"
                    f"Price: {result.price:.2f}\nSL: {sl:.2f} | TP: {tp:.2f}"
                )
                send_telegram_message(confirmation)
                active_trades[(side, zone)] = True
            else:
                error_msg = f"\u274c Order Failed\nRetcode: {result.retcode}\nMessage: {result.comment}"
                print(error_msg)
                send_telegram_message(error_msg)
        else:
            send_telegram_message("\u274c Order attempt returned None")

    trail_sl(SYMBOL, MAGIC)
    check_for_closed_trades()

def zones_equal(z1, z2):
    if len(z1) != len(z2):
        return False
    for a, b in zip(z1, z2):
        if abs(a['price'] - b['price']) > 1e-5 or a['time'] != b['time']:
            return False
    return True
