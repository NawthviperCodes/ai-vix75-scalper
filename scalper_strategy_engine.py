# === scalper_strategy_engine.py (Multi-Zone Trade Support + Reliable Cleanup + Trade Logging) ===

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from zone_detector import detect_zones, detect_fast_zones
from trade_decision_engine import trade_decision_engine
from telegram_notifier import send_telegram_message
from trade_executor import place_order, trail_sl
from performance_tracker import log_trade
import pytz

SYMBOL = "Volatility 75 Index"
TIMEFRAME_ZONE = mt5.TIMEFRAME_H1
TIMEFRAME_ENTRY = mt5.TIMEFRAME_M1
ZONE_LOOKBACK = 100
SL_BUFFER = 15000
TP_RATIO = 2
MAGIC = 77775
CHECK_RANGE = 30000

active_trades = {}  # key = (side, zone_price)
zone_touch_counts = {}
_last_demand_zones = []
_last_supply_zones = []
_last_fast_demand = []
_last_fast_supply = []
_last_zone_alert_time = None

def zones_equal(z1, z2):
    if len(z1) != len(z2):
        return False
    for a, b in zip(z1, z2):
        if abs(a['price'] - b['price']) > 1e-5 or a['time'] != b['time']:
            return False
    return True

def get_data(symbol, timeframe, bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_h1_trend(h1_df):
    h1_df['SMA50'] = h1_df['close'].rolling(50).mean()
    if len(h1_df) < 51:
        return None
    last = h1_df['close'].iloc[-1]
    sma = h1_df['SMA50'].iloc[-1]
    if last > sma:
        return "uptrend"
    elif last < sma:
        return "downtrend"
    else:
        return "sideways"

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
                sl = deal.sl
                tp = deal.tp
                strategy_mode = "unknown"
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

    trend = calculate_h1_trend(h1_df)
    if not trend:
        print("[ERROR] Not enough H1 data for trend.")
        return

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
            send_telegram_message("❌ Order placement failed: check your trade_executor function definition")
            return

        if result is not None:
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                confirmation = (
                    f"✅ ORDER PLACED\n{side.upper()} {SYMBOL}\n"
                    f"Price: {result.price:.2f}\nSL: {sl:.2f} | TP: {tp:.2f}"
                )
                send_telegram_message(confirmation)
                active_trades[(side, zone)] = True
            else:
                error_msg = f"❌ Order Failed\nRetcode: {result.retcode}\nMessage: {result.comment}"
                print(error_msg)
                send_telegram_message(error_msg)
        else:
            send_telegram_message("❌ Order attempt returned None")

    trail_sl(SYMBOL, MAGIC)
    check_for_closed_trades()
