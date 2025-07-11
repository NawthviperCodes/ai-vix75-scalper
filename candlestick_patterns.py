# candlestick_patterns.py

def is_bullish_pin_bar(open_, high, low, close, threshold=2.0):
    """
    Detects a bullish pin bar (long lower wick, small body at top).
    :param threshold: wick-to-body ratio to qualify as a pin bar
    """
    body = abs(close - open_)
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)

    return (
        lower_wick > body * threshold and       # Long lower wick
        upper_wick < body and                   # Small upper wick
        close > open_                           # Bullish body
    )


def is_bearish_pin_bar(open_, high, low, close, threshold=2.0):
    """
    Detects a bearish pin bar (long upper wick, small body at bottom).
    """
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low

    return (
        upper_wick > body * threshold and       # Long upper wick
        lower_wick < body and                   # Small lower wick
        close < open_                           # Bearish body
    )


def is_bullish_engulfing(prev_open, prev_close, open_, close):
    """
    Detects bullish engulfing pattern
    """
    return (
        prev_close < prev_open and              # Previous candle is bearish
        close > open_ and                       # Current candle is bullish
        close > prev_open and                   # Engulfs previous open
        open_ < prev_close                      # Engulfs previous close
    )


def is_bearish_engulfing(prev_open, prev_close, open_, close):
    """
    Detects bearish engulfing pattern
    """
    return (
        prev_close > prev_open and              # Previous candle is bullish
        close < open_ and                       # Current candle is bearish
        open_ > prev_close and                  # Engulfs previous close
        close < prev_open                       # Engulfs previous open
    )
