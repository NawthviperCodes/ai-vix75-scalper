# === trade_decision_engine.py (Adaptive Elite VIX75 Version) ===

from telegram_notifier import send_telegram_message
from candlestick_patterns import detect_patterns

RESET_BUFFER_POINTS = 1000
MAX_TOUCHES = 3
MAX_CANDLE_BODY_SIZE = 1500  # To avoid fakeouts
MIN_SL_DISTANCE = 500        # To avoid too-tight SL

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

    def update_touch_count(zone_id, candle_time, in_zone):
        if zone_id not in zone_touch_counts:
            zone_touch_counts[zone_id] = {
                'count': 0,
                'last_touch_time': candle_time,
                'was_outside_zone': False
            }
        zone_state = zone_touch_counts[zone_id]
        if not in_zone:
            zone_state['was_outside_zone'] = True
        if in_zone and zone_state['was_outside_zone']:
            if candle_time != zone_state['last_touch_time']:
                zone_state['count'] += 1
                zone_state['last_touch_time'] = candle_time
                zone_state['was_outside_zone'] = False
                return zone_state['count']
        return zone_touch_counts[zone_id]['count']

    def reset_touch_count(zone_id):
        if zone_id in zone_touch_counts:
            del zone_touch_counts[zone_id]

    def body_too_large(candle):
        return abs(candle.close - candle.open) > MAX_CANDLE_BODY_SIZE * point

    demand_price_check = last3_candles['low'].iloc[-2]
    supply_price_check = last3_candles['high'].iloc[-2]
    candle_time = last3_candles['time'].iloc[-2]

    all_zones = [("demand", demand_zones), ("supply", supply_zones)]

    for zone_type, zones in all_zones:
        for zone in zones:
            zone_id = zone['id']
            zone_low = zone.get('low')
            zone_high = zone.get('high')
            zone_mid = (zone_low + zone_high) / 2
            is_fast = "fast" in zone.get("type", "").lower()
            zone_strength = zone.get("strength", 0)
            lot_size = LOT_SIZE

            zone_label = f"{'FAST' if is_fast else 'STRICT'} {zone_type.upper()} ({zone_strength}%)"

            threshold = CHECK_RANGE * point
            dist = abs(demand_price_check - zone_mid) if zone_type == "demand" else abs(supply_price_check - zone_mid)
            in_zone = dist < threshold
            touch_number = update_touch_count(zone_id, candle_time, in_zone)

            # Too many touches? Skip
            if touch_number > MAX_TOUCHES:
                send_telegram_message(
                f"⛔ No trade: {zone_label} tested {touch_number} times. "
                f"Liquidity likely absorbed—waiting for a fresh imbalance.")
                continue

            candle = last3_candles.iloc[-1]
            prev_candle = last3_candles.iloc[-2]
            patterns = detect_patterns(last3_candles[-2:])

            if not patterns:
                continue

            # Skip oversized manipulation candles
            if body_too_large(candle):
                send_telegram_message(
              f"🚫 No trade: Oversized candle detected ({abs(candle.close - candle.open) / point:.0f} pts). "
              f"⚠️ Likely news spike or stop hunt. Waiting for cleaner price action."
)
                continue

            trade_side = "buy" if zone_type == "demand" else "sell"
            opposite_side = "sell" if trade_side == "buy" else "buy"
            key = (trade_side, zone_id)

            # Trend Filtering (only for strict trend-follow)
            if strategy_mode == "trend_follow":
                if (zone_type == "demand" and trend != "uptrend") or (zone_type == "supply" and trend != "downtrend"):
                    send_telegram_message(f"🚫 Skipped {zone_label} due to trend mismatch ({trend})")
                    continue

            # Pattern Confirmation
            confirmed = False
            reason = ""
            if "bullish_engulfing" in patterns and zone_type == "demand":
                confirmed = True
                reason = "bullish engulfing"
            elif "bearish_engulfing" in patterns and zone_type == "supply":
                confirmed = True
                reason = "bearish engulfing"
            elif "bullish_pin_bar" in patterns and zone_type == "demand":
                confirmed = True
                reason = "bullish pin bar"
            elif "bearish_pin_bar" in patterns and zone_type == "supply":
                confirmed = True
                reason = "bearish pin bar"
            elif "inside_bar" in patterns:
                confirmed = True
                reason = "inside bar breakout"
            elif "doji" in patterns:
                confirmed = True
                reason = "doji reversal"

            if confirmed and not active_trades.get(key):
                entry = candle.close
                sl = zone.get("buffered_sl") or (
                    min(candle.low, prev_candle.low) - SL_BUFFER * point if trade_side == "buy"
                    else max(candle.high, prev_candle.high) + SL_BUFFER * point
                )
                sl = round(sl, 2)
                risk = abs(entry - sl)
                if risk < MIN_SL_DISTANCE * point:
                    send_telegram_message(
                   f"⚠️ No trade: Stop loss too tight at {zone_label}. "
                   f"Skipping low RR setup—waiting for better risk conditions.")
                    continue

                tp = entry + TP_RATIO * risk if trade_side == "buy" else entry - TP_RATIO * risk

                send_telegram_message(
    f"✅ Trade Signal: {reason.upper()} at {zone_label}\n"
    f"📌 Entry: {entry:.2f} | 🛡️ SL: {sl:.2f} | 🎯 TP: {tp:.2f} | Lot: {lot_size:.3f}\n"
    f"📊 Trend: {trend.capitalize()} | Strategy: {strategy_mode.upper()}")

                signals.append({
                    "side": trade_side,
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "zone": zone_mid,
                    "lot": lot_size,
                    "reason": reason,
                    "zone_type": "fast" if is_fast else "strict",
                    "strategy": strategy_mode
                })

    return signals
