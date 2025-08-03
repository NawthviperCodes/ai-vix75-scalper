# === Full Backtest File Integrating All Strategy Components ===

import pandas as pd
from datetime import datetime

# === Custom Modules ===
from trend_filter import determine_trend
from scalper_strategy_engine import entry_conditions
from trade_decision_engine import trade_decision_engine

# Optional: candle pattern filters or breakout modules can be added similarly

# === CONFIG ===
DATA_FILE = "M15_data.csv"
SL_BUFFER = 15000
TP_RATIO = 1.5
RISK_PER_TRADE = 0.01
ACCOUNT_BALANCE = 1000
POINT = 1

# === Statistics Tracker ===
class BacktestStats:
    def __init__(self, initial_equity):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.equity = initial_equity
        self.peak_equity = initial_equity
        self.max_drawdown = 0

    def update(self, profit):
        self.total_trades += 1
        if profit > 0:
            self.wins += 1
        else:
            self.losses += 1
        self.equity += profit
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        drawdown = self.peak_equity - self.equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

    def print_stats(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades else 0
        print(f"Total Trades: {self.total_trades} | Wins: {self.wins} | Losses: {self.losses} | Win Rate: {win_rate:.2f}%")
        print(f"Equity: {self.equity:.2f} | Max Drawdown: {self.max_drawdown:.2f}")

# === Load Data ===
df = pd.read_csv(DATA_FILE, sep="\t")
df['time'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'])
df.rename(columns={
    '<OPEN>': 'open',
    '<HIGH>': 'high',
    '<LOW>': 'low',
    '<CLOSE>': 'close'
}, inplace=True)

df = df[['time', 'open', 'high', 'low', 'close']]

# === Add Trend and Signal Columns ===
df = determine_trend(df)  # Adds 'trend' column ("up", "down", or None)

# === Backtest Engine ===
stats = BacktestStats(initial_equity=ACCOUNT_BALANCE)
equity_curve = [ACCOUNT_BALANCE]
open_positions = []
trade_history = []

for i in range(50, len(df) - 10):
    candle = df.iloc[i]
    future = df.iloc[i+1:i+11]  # next 10 candles
    price = candle['close']

    # Entry condition
    signal = entry_conditions(df.iloc[i-10:i+1])  # Pass slice to decision logic
    trend = candle['trend']

    if signal == "buy" and trend == "up":
        sl = price - SL_BUFFER
        tp = price + (TP_RATIO * SL_BUFFER)
        trade_type = "buy"
    elif signal == "sell" and trend == "down":
        sl = price + SL_BUFFER
        tp = price - (TP_RATIO * SL_BUFFER)
        trade_type = "sell"
    else:
        continue  # No valid trade

    # Simulate Trade
    result = "none"
    for _, f in future.iterrows():
        if trade_type == "buy":
            if f['low'] <= sl:
                result = "loss"
                exit_price = sl
                break
            elif f['high'] >= tp:
                result = "win"
                exit_price = tp
                break
        else:
            if f['high'] >= sl:
                result = "loss"
                exit_price = sl
                break
            elif f['low'] <= tp:
                result = "win"
                exit_price = tp
                break

    if result != "none":
        points = abs(exit_price - price)
        lots = (ACCOUNT_BALANCE * RISK_PER_TRADE) / SL_BUFFER
        profit = points * lots if result == "win" else -points * lots
        stats.update(profit)
        trade_history.append({
            "time": candle['time'],
            "type": trade_type,
            "entry": price,
            "exit": exit_price,
            "result": result,
            "profit": profit
        })

    equity_curve.append(stats.equity)

# === Final Output ===
print("\n=== Final Stats ===")
stats.print_stats()

print("\n=== Trade History ===")
for t in trade_history:
    print(f"{t['time']} | {t['type'].upper()} | Entry: {t['entry']:.2f} | Exit: {t['exit']:.2f} | Result: {t['result']} | Profit: {t['profit']:.2f}")
