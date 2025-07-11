# === performance_tracker.py (Advanced Summary + Live Stats) ===
import csv
from datetime import datetime, date, timedelta
import os
import matplotlib.pyplot as plt
from telegram_notifier import send_telegram_message

log_file = "trade_log.csv"

def init_log():
    if not os.path.exists(log_file):
        with open(log_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Entry Time", "Exit Time", "Side", "Entry", "Exit", "Profit", "Result",
                "Strategy Mode", "Stop Loss", "Take Profit"
            ])

def log_trade(entry_time, exit_time, side, entry_price, exit_price, profit, result, strategy_mode, sl, tp, silent=False):
    with open(log_file, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            entry_time, exit_time, side.upper(), entry_price, exit_price,
            profit, result.lower(), strategy_mode, sl, tp
        ])

    if not silent:
        msg = (
            f"📈 Trade Closed: {result.upper()}\n"
            f"Mode: {strategy_mode.upper()} | Side: {side.upper()}\n"
            f"Entry: {entry_price:.2f} → Exit: {exit_price:.2f}\n"
            f"Profit: ${profit:.2f} | SL: {sl:.2f}, TP: {tp:.2f}\n"
            f"Time: {entry_time} → {exit_time}"
        )
        send_telegram_message(msg)

def send_daily_summary():
    today = date.today()
    if not os.path.exists(log_file):
        return

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        trades_today = [row for row in reader if valid_date(row["Exit Time"]) and datetime.strptime(row["Exit Time"], "%Y-%m-%d %H:%M:%S").date() == today]

    if not trades_today:
        send_telegram_message("📊 No trades executed today.")
        return

    summary_msg, breakdown_msg = generate_summary(trades_today, title=f"📅 Daily Summary for {today.strftime('%Y-%m-%d')}")
    send_telegram_message(summary_msg)
    send_telegram_message(breakdown_msg)

    send_overall_performance()
    send_weekly_summary()

def valid_date(dt):
    try:
        datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
        return True
    except:
        return False

def generate_summary(trades, title="📊 Summary"):
    total_profit = 0
    wins = 0
    losses = 0
    sl_list, tp_list = [], []
    trade_details = []

    for row in trades:
        try:
            profit = float(row['Profit'])
            total_profit += profit
            sl_list.append(float(row['Stop Loss']))
            tp_list.append(float(row['Take Profit']))
            result = row['Result'].lower()
            trade_details.append((row['Side'], float(row['Entry']), float(row['Exit']), profit, result))
            if result == "win":
                wins += 1
            elif result == "loss":
                losses += 1
        except:
            continue

    total_trades = wins + losses
    win_rate = (wins / total_trades) * 100 if total_trades else 0
    most_common_side = max(set([t[0] for t in trade_details]), key=[t[0] for t in trade_details].count)
    avg_sl = sum(sl_list) / len(sl_list) if sl_list else 0
    avg_tp = sum(tp_list) / len(tp_list) if tp_list else 0
    top_trade = max(trade_details, key=lambda x: x[3])
    worst_trade = min(trade_details, key=lambda x: x[3])

    summary = (
        f"{title}\n"
        f"Trades: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%\n"
        f"Total Profit: ${total_profit:.2f} | Avg SL: {avg_sl:.1f} | Avg TP: {avg_tp:.1f}\n\n"
        f"Top Trade ✅\n{top_trade[0]} | Entry: {top_trade[1]:.2f} → Exit: {top_trade[2]:.2f} | Profit: ${top_trade[3]:.2f}\n\n"
        f"Worst Trade ❌\n{worst_trade[0]} | Entry: {worst_trade[1]:.2f} → Exit: {worst_trade[2]:.2f} | Loss: ${worst_trade[3]:.2f}\n\n"
        f"Most Active Side: {most_common_side.upper()}"
    )

    breakdown = "\n🔁 Trades:\n"
    for idx, (side, entry, exit_, profit, result) in enumerate(trade_details, 1):
        breakdown += f"{idx}. {side} | Entry: {entry:.2f} → Exit: {exit_:.2f} | ${profit:.2f} | {'✅ WIN' if result == 'win' else '❌ LOSS'}\n"

    return summary, breakdown

def send_overall_performance():
    if not os.path.exists(log_file):
        return

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        trades = list(reader)

    if not trades:
        return

    strategy_modes = {}
    equity, timestamps, profits = [], [], []
    running_total = 0
    wins = losses = 0

    for row in trades:
        try:
            profit = float(row["Profit"])
            strategy = row["Strategy Mode"]
            exit_time = datetime.strptime(row["Exit Time"], "%Y-%m-%d %H:%M:%S")
            profits.append(profit)
            timestamps.append(exit_time)
            running_total += profit
            equity.append(running_total)

            if row["Result"].lower() == "win":
                wins += 1
                strategy_modes.setdefault(strategy, {"win": 0, "loss": 0})["win"] += 1
            elif row["Result"].lower() == "loss":
                losses += 1
                strategy_modes.setdefault(strategy, {"win": 0, "loss": 0})["loss"] += 1
        except:
            continue

    plt.figure(figsize=(10, 4))
    plt.plot(timestamps, equity, marker='o', linestyle='-', color='blue')
    plt.title("📈 Equity Curve")
    plt.xlabel("Time")
    plt.ylabel("Cumulative Profit ($)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig("equity_curve.png")

    msg = (
        f"📊 Overall Performance:\n"
        f"Total Trades: {wins + losses}\n"
        f"Wins: {wins} | Losses: {losses} | Win Rate: {(wins / (wins + losses)) * 100:.2f}%\n"
        f"Total Profit: ${sum(profits):.2f}\n"
        f"📉 Equity curve saved as 'equity_curve.png'\n\n"
        f"📂 Strategy Mode Breakdown:\n"
    )
    for mode, stats in strategy_modes.items():
        total = stats['win'] + stats['loss']
        rate = (stats['win'] / total) * 100 if total > 0 else 0
        msg += f"- {mode}: {stats['win']}W/{stats['loss']}L → {rate:.1f}% win rate\n"

    send_telegram_message(msg)

def send_weekly_summary():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)

    if not os.path.exists(log_file):
        return

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        trades = [row for row in reader if valid_date(row["Exit Time"])]

    weekly_trades = []
    for row in trades:
        exit_date = datetime.strptime(row["Exit Time"], "%Y-%m-%d %H:%M:%S").date()
        if start_of_week <= exit_date <= end_of_week:
            weekly_trades.append(row)

    if not weekly_trades:
        return

    summary_msg, breakdown_msg = generate_summary(weekly_trades, title=f"📅 Weekly Summary ({start_of_week} → {end_of_week})")
    send_telegram_message(summary_msg)
    send_telegram_message(breakdown_msg)

def get_live_stats():
    today = datetime.now().date()
    pnl = 0
    trades_today = 0
    wins = 0
    losses = 0

    if not os.path.exists(log_file):
        return {
            "pnl": 0.00,
            "trades_today": 0,
            "win_rate": 0.0
        }

    with open(log_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                exit_time = datetime.strptime(row["Exit Time"], "%Y-%m-%d %H:%M:%S")
                if exit_time.date() == today:
                    profit = float(row["Profit"])
                    pnl += profit
                    trades_today += 1
                    if row["Result"].lower() == "win":
                        wins += 1
                    elif row["Result"].lower() == "loss":
                        losses += 1
            except:
                continue

    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0

    return {
        "pnl": round(pnl, 2),
        "trades_today": trades_today,
        "win_rate": round(win_rate, 1)
    }
