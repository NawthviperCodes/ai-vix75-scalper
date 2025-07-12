# --- Pro-Level Price Action Trade Decision Engine (Upgraded for VIX75 Beast Bot) ---

from datetime import datetime
from telegram_notifier import send_telegram_message
from candlestick_patterns import (
    is_bullish_pin_bar,
    is_bullish_engulfing,
    is_bearish_pin_bar,
    is_bearish_engulfing
)

RESET_BUFFER_POINTS = 1000

# 🚨 Optional Fast Zone Confirmations (set in .env)
import os
FAST_CONFIRMATION_ENABLED = os.getenv("FAST_CONFIRMATION_ENABLED", "False").lower() == "true"

def trade_decision_engine(
    symbol,
    point,
    current_price,
    trend,
    demand_zones,
    supply_zones,
    last3_candles,
    active_trades,
    zone_touch_counts,
    SL_BUFFER,
    TP_RATIO,
    CHECK_RANGE,
    LOT_SIZE,
    MAGIC,
    strategy_mode="trend_follow"
):
    signals = []

    def update_touch_count(zone_price, candle_time, in_zone):
        if zone_price not in zone_touch_counts:
            zone_touch_counts[zone_price] = {
                'count': 0,
                'last_touch_time': candle_time,
                'was_outside_zone': False
            }
        zone_state = zone_touch_counts[zone_price]
        if not in_zone:
            zone_state['was_outside_zone'] = True
        if in_zone and zone_state['was_outside_zone']:
            if candle_time != zone_state['last_touch_time']:
                zone_state['count'] += 1
                zone_state['last_touch_time'] = candle_time
                zone_state['was_outside_zone'] = False
                return zone_state['count']
        return None

    def reset_touch_count(zone_price):
        if zone_price in zone_touch_counts:
            del zone_touch_counts[zone_price]

    def candle_confirms_breakout(trend, candle, zone_low, zone_high):
        return (
            trend == "uptrend" and candle.close > zone_high or
            trend == "downtrend" and candle.close < zone_low
        )

    def has_wick_rejection(candle, direction="bullish", min_wick_ratio=1.5):
        body = abs(candle.close - candle.open)
        upper_wick = candle.high - max(candle.close, candle.open)
        lower_wick = min(candle.close, candle.open) - candle.low
        if body == 0:
            return False
        return (lower_wick / body) >= min_wick_ratio if direction == "bullish" else (upper_wick / body) >= min_wick_ratio

    def detect_false_breakout(prev, curr, zone_low, zone_high, direction):
        if direction == "bearish":
            return (
                prev.close > zone_high and curr.close < zone_high and
                is_bearish_engulfing(prev.open, prev.close, curr.open, curr.close)
            )
        elif direction == "bullish":
            return (
                prev.close < zone_low and curr.close > zone_low and
                is_bullish_engulfing(prev.open, prev.close, curr.open, curr.close)
            )
        return False

    demand_price_check = last3_candles['low'].iloc[-2]
    supply_price_check = last3_candles['high'].iloc[-2]
    candle_time = last3_candles['time'].iloc[-2]

    all_zones = [("demand", demand_zones), ("supply", supply_zones)]

    for zone_type, zones in all_zones:
        for zone in zones:
            zone_low = zone.get('low', zone['price'])
            zone_high = zone.get('high', zone['price'])
            zone_mid = (zone_low + zone_high) / 2
            zone_kind = zone.get('type', 'strict')
            zone_strength = zone.get('strength', 0)
            is_fast = "fast" in zone_kind.lower()
            lot_size = LOT_SIZE

            zone_type_label = zone_type.upper()
            zone_label = f"{'FAST' if is_fast else 'STRICT'} {zone_type_label} ({zone_strength}%)"

            threshold = CHECK_RANGE * point
            dist = abs(demand_price_check - zone_mid) if zone_type == "demand" else abs(supply_price_check - zone_mid)
            in_zone = dist < threshold
            touch_number = update_touch_count(zone_mid, candle_time, in_zone)

            candle = last3_candles.iloc[-1]
            prev_candle = last3_candles.iloc[-2]

            key = ("buy" if zone_type == "demand" else "sell", zone_mid)

            if touch_number:
                send_telegram_message(f"⚠️ Price touched {zone_label} at {zone_mid:.2f} (touch {touch_number})")

                # Trend filter (safe mode only)
                if strategy_mode == "trend_follow":
                    if (zone_type == "demand" and trend != "uptrend") or (zone_type == "supply" and trend != "downtrend"):
                        msg = f"⛔️ Skipped: trend mismatch at {zone_label} (trend: {trend})"
                        print(msg)
                        send_telegram_message(msg)
                        continue

                confirmed = False
                reason = ""

                # 🚀 Aggressive mode: skip confirmations for fast zones unless enabled
                if strategy_mode == "aggressive" and is_fast and not FAST_CONFIRMATION_ENABLED:
                    confirmed = True
                    reason = "FAST zone auto-entry (aggressive mode)"
                else:
                    # Breakout confirmation
                    if candle_confirms_breakout(trend, candle, zone_low, zone_high):
                        confirmed = True
                        reason = "breakout continuation"

                    # Rejection confirmations
                    elif (zone_type == "demand" and is_bullish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)) or \
                         (zone_type == "supply" and is_bearish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)):
                        confirmed = True
                        reason = "engulfing rejection"

                    elif (zone_type == "demand" and is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close)) or \
                         (zone_type == "supply" and is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close)):
                        confirmed = True
                        reason = "pin bar rejection"

                    elif strategy_mode == "aggressive" and has_wick_rejection(candle, direction="bullish" if zone_type == "demand" else "bearish"):
                        confirmed = True
                        reason = "wick rejection"

                if confirmed and not active_trades.get(key):
                    entry = candle.close
                    sl = (min(candle.low, prev_candle.low) - SL_BUFFER * point) if zone_type == "demand" else \
                         (max(candle.high, prev_candle.high) + SL_BUFFER * point)
                    tp = entry + TP_RATIO * (entry - sl) if zone_type == "demand" else \
                         entry - TP_RATIO * (sl - entry)

                    send_telegram_message(f"✅ Entry reason: {reason}")
                    send_telegram_message(
                        f"📥 SIGNAL: {zone_label} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot_size:.3f}"
                    )
                    signals.append({
                        "side": key[0],
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "zone": zone_mid,
                        "lot": lot_size
                    })

                elif not confirmed:
                    send_telegram_message(f"⛔️ Skipped: no confirmation at {zone_label}")

            # 🔄 False Breakout Detection
            reverse_side = "buy" if zone_type == "supply" else "sell"
            reverse_key = (reverse_side, zone_mid)
            if detect_false_breakout(prev_candle, candle, zone_low, zone_high, direction="bullish" if zone_type == "supply" else "bearish"):
                if not active_trades.get(reverse_key):
                    entry = candle.close
                    sl = (max(candle.high, prev_candle.high) + SL_BUFFER * point) if reverse_side == "sell" else \
                         (min(candle.low, prev_candle.low) - SL_BUFFER * point)
                    tp = entry - TP_RATIO * (sl - entry) if reverse_side == "sell" else \
                         entry + TP_RATIO * (entry - sl)

                    send_telegram_message(f"🔄 False breakout reversal at {zone_label} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot_size:.3f}")
                    signals.append({
                        "side": reverse_side,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "zone": zone_mid,
                        "lot": lot_size
                    })

            if touch_number == 4:
                send_telegram_message(f"⚠️ 4th touch at {zone_label} - possible breakout")
                reset_touch_count(zone_mid)

    return signals
