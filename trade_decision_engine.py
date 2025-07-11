from datetime import datetime
from telegram_notifier import send_telegram_message
from candlestick_patterns import (
    is_bullish_pin_bar,
    is_bullish_engulfing,
    is_bearish_pin_bar,
    is_bearish_engulfing
)

RESET_BUFFER_POINTS = 1000

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

    def candle_confirms_breakout(trend, candle, zone_price):
        return (trend == "uptrend" and candle.close > zone_price) or (trend == "downtrend" and candle.close < zone_price)

    def has_wick_rejection(candle, direction="bullish", min_wick_ratio=1.5):
        body = abs(candle.close - candle.open)
        upper_wick = candle.high - max(candle.close, candle.open)
        lower_wick = min(candle.close, candle.open) - candle.low
        if body == 0:
            return False
        return (lower_wick / body) >= min_wick_ratio if direction == "bullish" else (upper_wick / body) >= min_wick_ratio

    def detect_false_breakout(prev, curr, zone_price, direction):
        if direction == "bearish":
            return prev.close > zone_price and curr.close < zone_price and is_bearish_engulfing(prev.open, prev.close, curr.open, curr.close)
        elif direction == "bullish":
            return prev.close < zone_price and curr.close > zone_price and is_bullish_engulfing(prev.open, prev.close, curr.open, curr.close)
        return False

    demand_price_check = last3_candles['low'].iloc[-2]
    supply_price_check = last3_candles['high'].iloc[-2]
    candle_time = last3_candles['time'].iloc[-2]

    all_zones = [("demand", demand_zones), ("supply", supply_zones)]

    for zone_type, zones in all_zones:
        for zone in zones:
            zone_price = zone['price']
            zone_kind = zone.get('type', 'strict')
            is_fast = "fast" in zone_kind.lower()
            lot_size = LOT_SIZE
            
            
            print(f"[DEBUG] Zone: {zone_price:.2f} | Fast: {is_fast} | Final Lot: {lot_size:.3f}")

            zone_type_label = zone_type.upper()
            zone_label = f"{'FAST' if is_fast else 'STRICT'} {zone_type_label}"

            threshold = CHECK_RANGE * point
            dist = abs(demand_price_check - zone_price) if zone_type == "demand" else abs(supply_price_check - zone_price)
            in_zone = dist < threshold
            touch_number = update_touch_count(zone_price, candle_time, in_zone)

            candle = last3_candles.iloc[-1]
            prev_candle = last3_candles.iloc[-2]

            key = ("buy" if zone_type == "demand" else "sell", zone_price)

            if touch_number:
                send_telegram_message(f"⚠️ Price touched {zone_label} zone at {zone_price:.2f} (touch {touch_number})")

                # Trend-following filter
                if strategy_mode == "trend_follow":
                    if (zone_type == "demand" and trend != "uptrend") or (zone_type == "supply" and trend != "downtrend"):
                        msg = f"⛔️ Skipped: trend mismatch at {zone_label} zone {zone_price:.2f} (trend: {trend})"
                        print(msg)
                        send_telegram_message(msg)
                        continue

                confirmed = False
                reason = ""

                if (zone_type == "demand" and is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close)) or \
                   (zone_type == "supply" and is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close)):
                    confirmed = True
                    reason = "pin bar"
                elif (zone_type == "demand" and is_bullish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)) or \
                     (zone_type == "supply" and is_bearish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close)):
                    confirmed = True
                    reason = "engulfing"
                elif candle_confirms_breakout(trend, candle, zone_price):
                    confirmed = True
                    reason = "breakout"

                # Aggressive mode wick rejection
                if not confirmed and strategy_mode == "aggressive" and has_wick_rejection(
                    candle, direction="bullish" if zone_type == "demand" else "bearish"):
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
                        "zone": zone_price,
                        "lot": lot_size
                    })
                elif not confirmed:
                    send_telegram_message(f"⛔️ Skipped: no confirmation at {zone_label} zone {zone_price:.2f}")

            # === False Breakout Reversal ===
            reverse_side = "sell" if zone_type == "demand" else "buy"
            reverse_key = (reverse_side, zone_price)
            if detect_false_breakout(prev_candle, candle, zone_price, direction="bearish" if zone_type == "demand" else "bullish"):
                if not active_trades.get(reverse_key):
                    entry = candle.close
                    sl = (max(candle.high, prev_candle.high) + SL_BUFFER * point) if zone_type == "demand" else \
                         (min(candle.low, prev_candle.low) - SL_BUFFER * point)
                    tp = entry - TP_RATIO * (sl - entry) if zone_type == "demand" else \
                         entry + TP_RATIO * (entry - sl)

                    send_telegram_message(
                        f"🔄 False breakout reversal at {zone_label} zone {zone_price:.2f} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f} | Lot: {lot_size:.3f}"
                    )
                    signals.append({
                        "side": reverse_side,
                        "entry": entry,
                        "sl": sl,
                        "tp": tp,
                        "zone": zone_price,
                        "lot": lot_size
                    })

            # Reset after 4 touches
            if touch_number == 4:
                send_telegram_message(f"⚠️ 4th touch at {zone_label} zone {zone_price:.2f} - possible breakout")
                reset_touch_count(zone_price)

    return signals
