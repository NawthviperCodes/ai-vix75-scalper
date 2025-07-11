# === performance_tracker.py (Enhanced Daily Summary, Silent Logging Support) ===
import csv
from datetime import datetime, date
import os
from telegram_notifier import send_telegram_message

log_file = "trade_log.csv"

def init_log():
    if not os.path.exists(log_file):
        with open(log_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Entry Time", "Exit Time", "Side", "Entry", "Exit", "Profit", "Result"])

def log_trade(entry_time, exit_time, side, entry_price, exit_price, profit, result, silent=False):
    with open(log_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            entry_time, exit_time, side.upper(), entry_price, exit_price, profit, result
        ])

    if not silent:
        msg = (
            f"📈 Trade Closed: {result.upper()}\n"
            f"Side: {side.upper()}\n"
            f"Entry: {entry_price:.2f} → Exit: {exit_price:.2f}\n"
            f"Profit: ${profit:.2f}\n"
            f"Time: {entry_time} → {exit_time}"
        )
        send_telegram_message(msg)

def send_daily_summary():
    today = date.today()
    trades_today = []
    total_profit = 0
    wins = 0
    losses = 0
    trade_details = []

    if not os.path.exists(log_file):
        return

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                exit_time = datetime.strptime(row['Exit Time'], "%Y-%m-%d %H:%M:%S")
                if exit_time.date() == today:
                    profit = float(row['Profit'])
                    result = row['Result'].lower()
                    total_profit += profit
                    trades_today.append(row)
                    trade_details.append((row['Side'], float(row['Entry']), float(row['Exit']), profit, result))
                    if result == "win":
                        wins += 1
                    elif result == "loss":
                        losses += 1
            except:
                continue

    if not trades_today:
        send_telegram_message("📊 No trades executed today.")
        return

    total_trades = wins + losses
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    most_common_side = max(set([t[0] for t in trade_details]), key=[t[0] for t in trade_details].count)

    top_trade = max(trade_details, key=lambda x: x[3])
    worst_trade = min(trade_details, key=lambda x: x[3])

    summary = (
        f"📅 Summary for {today.strftime('%Y-%m-%d')}\n"
        f"Trades: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%\n"
        f"Total Profit: ${total_profit:.2f}\n\n"
        f"Top Trade ✅\n{top_trade[0]} | Entry: {top_trade[1]:.2f} → Exit: {top_trade[2]:.2f} | Profit: ${top_trade[3]:.2f}\n\n"
        f"Worst Trade ❌\n{worst_trade[0]} | Entry: {worst_trade[1]:.2f} → Exit: {worst_trade[2]:.2f} | Loss: ${worst_trade[3]:.2f}\n\n"
        f"Most Active Side: {most_common_side.upper()}"
    )

    send_telegram_message(summary)

    # Optional detailed breakdown
    breakdown = "\n🔁 Trades:\n"
    for idx, (side, entry, exit_, profit, result) in enumerate(trade_details, 1):
        breakdown += f"{idx}. {side} | Entry: {entry:.2f} → Exit: {exit_:.2f} | ${profit:.2f} | {'✅ WIN' if result == 'win' else '❌ LOSS'}\n"
    send_telegram_message(breakdown)