# === trade_decision_engine.py ===
# (Enhanced with rate limiting and message consolidation)

from datetime import datetime
from telegram_notifier import send_telegram_message
from candlestick_patterns import (
    is_bullish_pin_bar,
    is_bullish_engulfing,
    is_bearish_pin_bar,
    is_bearish_engulfing,
    is_hammer,
    is_shooting_star,
    is_bullish_marubozu,
    is_bearish_marubozu,
    is_harami,
    is_doji
)

RESET_BUFFER_POINTS = 1000
PATTERN_COOLDOWN = 300
_last_pattern_used = {}

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
    strategy_mode="trend_follow",
    breaker_block=None
):
    signals = []
    candle = last3_candles.iloc[-1]
    prev_candle = last3_candles.iloc[-2]
    prev_prev_candle = last3_candles.iloc[-3] if len(last3_candles) >= 3 else prev_candle
    patterns = []

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
        if trend == "uptrend" and candle.close > zone_price:
            return True
        elif trend == "downtrend" and candle.close < zone_price:
            return True
        return False

    def has_wick_rejection(candle, direction="bullish", min_wick_ratio=1.5):
        body = abs(candle.close - candle.open)
        upper_wick = candle.high - max(candle.close, candle.open)
        lower_wick = min(candle.close, candle.open) - candle.low
        if body == 0:
            return False
        return (lower_wick if direction == "bullish" else upper_wick) / body >= min_wick_ratio

    def detect_false_breakout(prev, curr, zone_price, direction):
        if direction == "bearish":
            return prev.close > zone_price and curr.close < zone_price and is_bearish_engulfing(
                prev.open, prev.close, curr.open, curr.close
            )
        elif direction == "bullish":
            return prev.close < zone_price and curr.close > zone_price and is_bullish_engulfing(
                prev.open, prev.close, curr.open, curr.close
            )
        return False

    def detect_zone_confirmation_patterns(candle, prev_candle, prev_prev_candle):
        detected = []
        if is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close):
            detected.append("bullish_pin_bar")
        if is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close):
            detected.append("bearish_pin_bar")
        if is_hammer(candle.open, candle.high, candle.low, candle.close):
            detected.append("hammer")
        if is_shooting_star(candle.open, candle.high, candle.low, candle.close):
            detected.append("shooting_star")
        if is_bullish_marubozu(candle.open, candle.high, candle.low, candle.close):
            detected.append("bullish_marubozu")
        if is_bearish_marubozu(candle.open, candle.high, candle.low, candle.close):
            detected.append("bearish_marubozu")
        if is_doji(candle.open, candle.close, candle.high, candle.low):
            detected.append("doji")
        if is_bullish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close):
            detected.append("bullish_engulfing")
        if is_bearish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close):
            detected.append("bearish_engulfing")
        return detected if detected else []

    patterns = detect_zone_confirmation_patterns(candle, prev_candle, prev_prev_candle)
    if patterns and strategy_mode == "aggressive":
        send_telegram_message(f"🔍 Aggressive Mode Patterns: {', '.join(patterns)}", priority="low")

    demand_price_check = last3_candles['low'].iloc[-2]
    supply_price_check = last3_candles['high'].iloc[-2]
    candle_time = last3_candles['time'].iloc[-2]
    range_buffer = CHECK_RANGE * (1.5 if strategy_mode == "aggressive" else 1.0)

    # === DEMAND ZONES ===
    for zone in demand_zones:
        zone_price = zone['price']
        dist = abs(demand_price_check - zone_price)
        in_zone = dist < range_buffer * point
        touch_number = update_touch_count(zone_price, candle_time, in_zone)

        if touch_number:
            send_telegram_message(f"⚠️ Price touched DEMAND zone at {zone_price:.2f} (touch {touch_number})", priority="low")

            if strategy_mode == "trend_follow" and trend != "uptrend":
                send_telegram_message(f"⛔️ Skipped: trend mismatch at DEMAND zone {zone_price:.2f} (trend: {trend})", priority="low")
                continue

            confirmed = False
            confirmation_reasons = []

            if strategy_mode == "aggressive":
                if patterns and any(p in patterns for p in ["bullish_pin_bar", "hammer", "bullish_engulfing", "bullish_marubozu"]):
                    confirmed = True
                    confirmation_reasons.append(f"aggressive pattern ({', '.join(patterns)})")
                elif has_wick_rejection(candle, direction="bullish", min_wick_ratio=1.2):
                    confirmed = True
                    confirmation_reasons.append("strong bullish wick rejection")
            else:
                if is_bullish_pin_bar(candle.open, candle.high, candle.low, candle.close):
                    confirmed = True
                    confirmation_reasons.append("bullish pin bar")
                elif is_bullish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close):
                    confirmed = True
                    confirmation_reasons.append("bullish engulfing")

            if candle_confirms_breakout(trend, candle, zone_price):
                confirmed = True
                confirmation_reasons.append("breakout confirmation")
            if has_wick_rejection(candle, direction="bullish"):
                confirmed = True
                confirmation_reasons.append("bullish wick rejection")
                
            if breaker_block and breaker_block['valid'] and breaker_block['type'] == "bullish":
                if zone['zone_low'] <= breaker_block['breaker_line'] <= zone['zone_high']:
                    confirmed = True
                    confirmation_reasons.append("breaker block (bullish)")

            if confirmed and not active_trades.get("buy"):
                entry = candle.close
                sl = candle.low - SL_BUFFER * point
                tp = entry + TP_RATIO * (entry - sl)
                signals.append({
                    "side": "buy",
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "zone": zone_price,
                    "reason": ", ".join(confirmation_reasons),
                    "patterns": patterns,
                    "lot": LOT_SIZE
                })
                send_telegram_message(
                    f"🟢 BUY Signal | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}\n"
                    f"Zone: {zone_price:.2f} | Reason: {', '.join(confirmation_reasons)}",
                    priority="high"
                )
            elif not confirmed:
                send_telegram_message(f"⛔️ Skipped: no confirmation at DEMAND zone {zone_price:.2f}", priority="low")

        if detect_false_breakout(prev_candle, candle, zone_price, direction="bearish") and not active_trades.get("sell"):
            entry = candle.close
            sl = candle.high + SL_BUFFER * point
            tp = entry - TP_RATIO * (sl - entry)
            signals.append({
                "side": "sell",
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "zone": zone_price,
                "reason": "false breakout reversal",
                "lot": LOT_SIZE
            })
            send_telegram_message(f"🔄 False breakout reversal at DEMAND zone {zone_price:.2f} → SELL", priority="normal")
            send_telegram_message(f"🔴 SELL Signal | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", priority="high")

        if touch_number == 4:
            send_telegram_message(f"⚠️ 4th touch at DEMAND zone {zone_price:.2f} - possible breakout", priority="normal")
            reset_touch_count(zone_price)

    # === SUPPLY ZONES ===
    for zone in supply_zones:
        zone_price = zone['price']
        dist = abs(supply_price_check - zone_price)
        in_zone = dist < range_buffer * point
        touch_number = update_touch_count(zone_price, candle_time, in_zone)

        if touch_number:
            send_telegram_message(f"⚠️ Price touched SUPPLY zone at {zone_price:.2f} (touch {touch_number})", priority="low")

            if strategy_mode == "trend_follow" and trend != "downtrend":
                send_telegram_message(f"⛔️ Skipped: trend mismatch at SUPPLY zone {zone_price:.2f} (trend: {trend})", priority="low")
                continue

            confirmed = False
            confirmation_reasons = []

            if strategy_mode == "aggressive":
                if patterns and any(p in patterns for p in ["bearish_pin_bar", "shooting_star", "bearish_engulfing", "bearish_marubozu"]):
                    confirmed = True
                    confirmation_reasons.append(f"aggressive pattern ({', '.join(patterns)})")
                elif has_wick_rejection(candle, direction="bearish", min_wick_ratio=1.2):
                    confirmed = True
                    confirmation_reasons.append("strong bearish wick rejection")
            else:
                if is_bearish_pin_bar(candle.open, candle.high, candle.low, candle.close):
                    confirmed = True
                    confirmation_reasons.append("bearish pin bar")
                elif is_bearish_engulfing(prev_candle.open, prev_candle.close, candle.open, candle.close):
                    confirmed = True
                    confirmation_reasons.append("bearish engulfing")

            if candle_confirms_breakout(trend, candle, zone_price):
                confirmed = True
                confirmation_reasons.append("breakout confirmation")
            if has_wick_rejection(candle, direction="bearish"):
                confirmed = True
                confirmation_reasons.append("bearish wick rejection")
                
            if breaker_block and breaker_block['valid'] and breaker_block['type'] == "bearish":
                if zone['zone_low'] <= breaker_block['breaker_line'] <= zone['zone_high']:
                    confirmed = True
                    confirmation_reasons.append("breaker block (bearish)")

            if confirmed and not active_trades.get("sell"):
                entry = candle.close
                sl = candle.high + SL_BUFFER * point
                tp = entry - TP_RATIO * (sl - entry)
                signals.append({
                    "side": "sell",
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "zone": zone_price,
                    "reason": ", ".join(confirmation_reasons),
                    "patterns": patterns,
                    "lot": LOT_SIZE
                })
                send_telegram_message(
                    f"🔴 SELL Signal | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}\n"
                    f"Zone: {zone_price:.2f} | Reason: {', '.join(confirmation_reasons)}",
                    priority="high"
                )
            elif not confirmed:
                send_telegram_message(f"⛔️ Skipped: no confirmation at SUPPLY zone {zone_price:.2f}", priority="low")

        if detect_false_breakout(prev_candle, candle, zone_price, direction="bullish") and not active_trades.get("buy"):
            entry = candle.close
            sl = candle.low - SL_BUFFER * point
            tp = entry + TP_RATIO * (entry - sl)
            signals.append({
                "side": "buy",
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "zone": zone_price,
                "reason": "false breakout reversal",
                "lot": LOT_SIZE
            })
            send_telegram_message(f"🔄 False breakout reversal at SUPPLY zone {zone_price:.2f} → BUY", priority="normal")
            send_telegram_message(f"🟢 BUY Signal | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", priority="high")

        if touch_number == 4:
            send_telegram_message(f"⚠️ 4th touch at SUPPLY zone {zone_price:.2f} - possible breakout", priority="normal")
            reset_touch_count(zone_price)

    # === PURE AGGRESSIVE PATTERN SCALP ===
    current_time = datetime.now()
    min_distance = 75000  # VIX75 requires 75k points

    for pattern in patterns:
        last_used = _last_pattern_used.get(pattern)
        if last_used and (current_time - last_used).total_seconds() < PATTERN_COOLDOWN:
            cooldown = (current_time - last_used).total_seconds()
            send_telegram_message(f"⏳ Cooldown active for pattern: {pattern} ({int(cooldown)}s ago)", priority="low")
            continue

        full_range = candle.high - candle.low
        body_range = (
            candle.close - candle.low if "bullish" in pattern or pattern in ["marubozu", "hammer", "doji"]
            else candle.high - candle.close
        )

        if body_range >= min_distance and full_range >= min_distance * 1.5:
            if "bearish" in pattern:
                sl = candle.high + min_distance
                tp = candle.close - (TP_RATIO * min_distance)
                signals.append({
                    "side": "sell",
                    "entry": candle.close,
                    "sl": sl,
                    "tp": tp,
                    "reason": f"Aggressive {pattern} pattern",
                    "lot": LOT_SIZE
                })
                send_telegram_message(f"📉 Aggressive SELL | Entry: {candle.close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", priority="high")
            else:
                sl = candle.low - min_distance
                tp = candle.close + (TP_RATIO * min_distance)
                signals.append({
                    "side": "buy",
                    "entry": candle.close,
                    "sl": sl,
                    "tp": tp,
                    "reason": f"Aggressive {pattern} pattern",
                    "lot": LOT_SIZE
                })
                send_telegram_message(f"📈 Aggressive BUY | Entry: {candle.close:.2f} | SL: {sl:.2f} | TP: {tp:.2f}", priority="high")

            _last_pattern_used[pattern] = current_time

    if not signals:
        send_telegram_message("📭 No signal triggered. Market may not be near any active zone.", priority="low")

    return signals