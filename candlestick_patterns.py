# === candlestick_patterns.py (Enhanced for VIX75 Smart Detection) ===

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
    return (body / range_) < threshold


def is_inside_bar(prev_high, prev_low, curr_high, curr_low):
    return curr_high < prev_high and curr_low > prev_low


def detect_patterns(df):
    """
    Scans last 2 candles and returns any confirmed VIX75 patterns.
    Requires df to be a DataFrame with columns: open, high, low, close
    """
    if len(df) < 2:
        return None

    prev = df.iloc[-2]
    curr = df.iloc[-1]

    patterns = []

    if is_bullish_engulfing(prev.open, prev.close, curr.open, curr.close):
        patterns.append("bullish_engulfing")
    if is_bearish_engulfing(prev.open, prev.close, curr.open, curr.close):
        patterns.append("bearish_engulfing")
    if is_bullish_pin_bar(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bullish_pin_bar")
    if is_bearish_pin_bar(curr.open, curr.high, curr.low, curr.close):
        patterns.append("bearish_pin_bar")
    if is_doji(curr.open, curr.close, curr.high, curr.low):
        patterns.append("doji")
    if is_inside_bar(prev.high, prev.low, curr.high, curr.low):
        patterns.append("inside_bar")

    return patterns if patterns else None
