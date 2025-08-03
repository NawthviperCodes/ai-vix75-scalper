# === candlestick_patterns.py (Volume-Free Price Action Patterns) ===

def is_bullish_pin_bar(open_, high, low, close, threshold=2.0):
    body = abs(close - open_)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)
    return (
        lower_wick > body * threshold and
        upper_wick < body * 0.5 and
        close > open_
    )

def is_bearish_pin_bar(open_, high, low, close, threshold=2.0):
    body = abs(close - open_)
    upper_wick = high - max(close, open_)
    lower_wick = min(close, open_) - low
    return (
        upper_wick > body * threshold and
        lower_wick < body * 0.5 and
        close < open_
    )

def is_bullish_engulfing(prev_open, prev_close, open_, close, min_body_ratio=1.2):
    prev_body = abs(prev_close - prev_open)
    curr_body = abs(close - open_)
    return (
        prev_close < prev_open and
        close > open_ and
        close > prev_open and
        open_ < prev_close and
        curr_body > prev_body * min_body_ratio
    )

def is_bearish_engulfing(prev_open, prev_close, open_, close, min_body_ratio=1.2):
    prev_body = abs(prev_close - prev_open)
    curr_body = abs(open_ - close)
    return (
        prev_close > prev_open and
        close < open_ and
        open_ > prev_close and
        close < prev_open and
        curr_body > prev_body * min_body_ratio
    )

def is_doji(open_, close, high, low, threshold=0.1):
    body = abs(close - open_)
    range_ = high - low
    if range_ == 0:
        return False
    return (body / range_) < threshold

def is_inside_bar(prev_high, prev_low, curr_high, curr_low):
    return curr_high < prev_high and curr_low > prev_low

def is_hammer(open_, high, low, close, threshold=2.0):
    body = abs(close - open_)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)
    return (
        lower_wick > body * threshold and
        upper_wick < body and
        close > open_ and
        (high - low) > 3 * body
    )

def is_shooting_star(open_, high, low, close, threshold=2.0):
    body = abs(close - open_)
    upper_wick = high - max(close, open_)
    lower_wick = min(close, open_) - low
    return (
        upper_wick > body * threshold and
        lower_wick < body and
        close < open_ and
        (high - low) > 3 * body
    )

def is_bullish_marubozu(open_, high, low, close, wick_threshold=0.05):
    body = close - open_
    range_ = high - low
    if range_ == 0 or body <= 0:
        return False
    upper_wick = high - close
    lower_wick = open_ - low
    return (
        (upper_wick + lower_wick) < (range_ * wick_threshold) and
        body > range_ * 0.9
    )

def is_bearish_marubozu(open_, high, low, close, wick_threshold=0.05):
    body = open_ - close
    range_ = high - low
    if range_ == 0 or body <= 0:
        return False
    upper_wick = high - open_
    lower_wick = close - low
    return (
        (upper_wick + lower_wick) < (range_ * wick_threshold) and
        body > range_ * 0.9
    )

def is_harami(prev_open, prev_close, open_, close):
    prev_body = abs(prev_close - prev_open)
    curr_body = abs(close - open_)
    return (
        curr_body < prev_body * 0.5 and
        ((close > open_ and prev_close > prev_open and open_ > prev_open and close < prev_close) or
         (close < open_ and prev_close < prev_open and open_ < prev_open and close > prev_close))
    )

def detect_patterns(df):
    patterns = []
    if len(df) < 2:
        return []

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    if is_bullish_pin_bar(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bullish_pin_bar")
    if is_bearish_pin_bar(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bearish_pin_bar")
    if is_hammer(curr.open, curr.high, curr.low, curr.close):
        patterns.append("hammer_bullish")
    if is_shooting_star(curr.open, curr.high, curr.low, curr.close):
        patterns.append("shooting_star_bearish")
    if is_bullish_marubozu(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bullish_marubozu")
    if is_bearish_marubozu(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bearish_marubozu")
    if is_doji(curr.open, curr.close, curr.high, curr.low):
        direction = "bullish" if curr.close > prev.close else "bearish"
        patterns.append(f"{direction}_doji")

    if is_bullish_engulfing(prev.open, prev.close, curr.open, curr.close):
        patterns.append("bullish_engulfing")
    if is_bearish_engulfing(prev.open, prev.close, curr.open, curr.close):
        patterns.append("bearish_engulfing")
    if is_harami(prev.open, prev.close, curr.open, curr.close):
        direction = "bullish" if curr.close > curr.open else "bearish"
        patterns.append(f"{direction}_harami")
    if is_inside_bar(prev.high, prev.low, curr.high, curr.low):
        direction = "bullish" if curr.close > prev.close else "bearish"
        patterns.append(f"{direction}_inside_bar")

    return patterns
