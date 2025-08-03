# === VIX75 Backtest Engine (Filtered from 2025-01-01) ===

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime
import os
from trade_decision_engine import trade_decision_engine
from breaker_block_detector import detect_breaker_block
from zone_detector import detect_zones

# === Disable Telegram for backtest ===
os.environ["DISABLE_TELEGRAM"] = "True"

# === Load and filter data ===
df = pd.read_csv("M15_data.csv", sep="\t")
df['datetime'] = pd.to_datetime(df['<DATE>'] + " " + df['<TIME>'])
df['spread'] = df['<SPREAD>']
df = df.rename(columns={
    '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close'
})
df = df[['datetime', 'open', 'high', 'low', 'close', 'spread']].copy()
df = df[df['datetime'] >= pd.to_datetime("2025-01-01")].reset_index(drop=True)

# === Config ===
TP_RATIO = 1.2
SL_BUFFER = 75000
CHECK_RANGE = 100000
LOT_SIZE = 0.001
MAGIC = 77775
POINT = 1
SLIPPAGE_POINTS = 1000
TRAILING_SL_TRIGGER = 1.0
TRAILING_SL_STEP = 0.5
PARTIAL_TP_RATIO = 1.0

# === Logs ===
trade_log = []
zone_stats = {
    'demand_confirmed': 0,
    'demand_rejected': 0,
    'supply_confirmed': 0,
    'supply_rejected': 0
}
equity = 0
equity_curve = []

# === Backtest Loop ===
for i in range(100, len(df) - 2):
    try:
        last3_candles = df.iloc[i-3:i].copy()
        last3_candles['time'] = last3_candles['datetime']
        current_candle = df.iloc[i]
        next_candle = df.iloc[i+1]

        h1_df = df.iloc[i-60:i].copy()
        h1_df = h1_df.rename(columns={'datetime': 'time'})

        demand_raw, _ = detect_zones(h1_df, zone_type="demand")
        supply_raw, _ = detect_zones(h1_df, zone_type="supply")

        demand_zones = [{
            'price': (z['zone_low'] + z['zone_high']) / 2,
            'type': 'strict_demand',
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        } for z in demand_raw]

        supply_zones = [{
            'price': (z['zone_low'] + z['zone_high']) / 2,
            'type': 'strict_supply',
            'time': z['timestamp'],
            'strength': z['strength'],
            'zone_low': z['zone_low'],
            'zone_high': z['zone_high']
        } for z in supply_raw]

        trend = "uptrend" if current_candle['close'] > df.iloc[i-50:i]['close'].mean() else "downtrend"
        breaker_block = detect_breaker_block(last3_candles)

        signals = trade_decision_engine(
            symbol="VIX75",
            point=POINT,
            current_price=current_candle['close'],
            trend=trend,
            demand_zones=demand_zones,
            supply_zones=supply_zones,
            last3_candles=last3_candles,
            active_trades={},
            zone_touch_counts={},
            SL_BUFFER=SL_BUFFER,
            TP_RATIO=TP_RATIO,
            CHECK_RANGE=CHECK_RANGE,
            LOT_SIZE=LOT_SIZE,
            MAGIC=MAGIC,
            strategy_mode="aggressive",
            breaker_block=breaker_block
        )

        for zone in demand_zones:
            zone_stats['demand_confirmed' if any(sig['zone'] == zone['price'] and sig['side'] == 'buy' for sig in signals) else 'demand_rejected'] += 1

        for zone in supply_zones:
            zone_stats['supply_confirmed' if any(sig['zone'] == zone['price'] and sig['side'] == 'sell' for sig in signals) else 'supply_rejected'] += 1

        for signal in signals:
            mid_price = current_candle['close']
            spread = current_candle['spread']
            slippage = np.random.randint(0, SLIPPAGE_POINTS)

            if signal['side'] == "buy":
                entry = mid_price + spread / 2 + slippage
                r_value = entry - signal['sl']
                partial_tp = entry + PARTIAL_TP_RATIO * r_value
                final_tp = entry + TP_RATIO * r_value
                sl = signal['sl']
            else:
                entry = mid_price - spread / 2 - slippage
                r_value = signal['sl'] - entry
                partial_tp = entry - PARTIAL_TP_RATIO * r_value
                final_tp = entry - TP_RATIO * r_value
                sl = signal['sl']

            result = ""
            profit = 0

            if signal['side'] == "buy":
                if next_candle['low'] <= sl:
                    result = "LOSS"
                    exit_price = sl
                    profit = exit_price - entry
                elif next_candle['high'] >= final_tp:
                    result = "WIN"
                    exit_price = final_tp
                    profit = r_value * TP_RATIO
                elif next_candle['high'] >= partial_tp:
                    result = "PARTIAL"
                    exit_price = entry + r_value * TRAILING_SL_STEP
                    profit = r_value * 0.5

            elif signal['side'] == "sell":
                if next_candle['high'] >= sl:
                    result = "LOSS"
                    exit_price = sl
                    profit = entry - exit_price
                elif next_candle['low'] <= final_tp:
                    result = "WIN"
                    exit_price = final_tp
                    profit = r_value * TP_RATIO
                elif next_candle['low'] <= partial_tp:
                    result = "PARTIAL"
                    exit_price = entry - r_value * TRAILING_SL_STEP
                    profit = r_value * 0.5

            if result:
                equity += profit
                equity_curve.append(equity)
                trade_log.append({
                    "time": current_candle['datetime'],
                    "side": signal['side'],
                    "entry": entry,
                    "sl": sl,
                    "tp": final_tp,
                    "exit": exit_price,
                    "result": result,
                    "profit": profit,
                    "reason": signal.get("reason", ""),
                    "patterns": ", ".join(signal.get("patterns", [])),
                    "zone": signal.get("zone", "")
                })

    except Exception as e:
        print(f"[❌ ERROR] i={i} | {e}")

# === Save and Summary ===
results_df = pd.DataFrame(trade_log)
results_df.to_csv("backtest_results.csv", index=False)

print("\n=== \U0001F4CA BACKTEST SUMMARY ===")
print(f"Total Trades : {len(results_df)}")
print(f"✅ Wins       : {len(results_df[results_df['result'] == 'WIN'])}")
print(f"❌ Losses     : {len(results_df[results_df['result'] == 'LOSS'])}")
print(f"🏆 Win Rate   : {len(results_df[results_df['result'] == 'WIN']) / len(results_df) * 100:.2f}%" if len(results_df) else "No trades.")
print(f"📈 Net Equity : {equity:.2f}")

print("\n=== \U0001F9E0 Zone Stats ===")
print(f"🟢 Demand Zones Confirmed : {zone_stats['demand_confirmed']}")
print(f"⛔️ Demand Zones Rejected  : {zone_stats['demand_rejected']}")
print(f"🔴 Supply Zones Confirmed : {zone_stats['supply_confirmed']}")
print(f"⛔️ Supply Zones Rejected  : {zone_stats['supply_rejected']}")

# === Plot Equity Curve ===
if equity_curve:
    plt.figure(figsize=(10, 4))
    plt.plot(equity_curve, label="Equity", color="green")
    plt.title("📈 Equity Curve (VIX75 Backtest)")
    plt.xlabel("Trade #")
    plt.ylabel("Equity")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.savefig("equity_curve.png")
    plt.show()
