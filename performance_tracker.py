import csv
from datetime import datetime, date
import os
from telegram_notifier import send_telegram_message  # Required for send_daily_summary

# Journal CSV file path
file_path = "trade_journal.csv"

def log_trade(entry_time, exit_time, side, entry_price, exit_price, profit, outcome,
              strategy_mode, zone_type, entry_reason, sl=None, tp=None):
    file_exists = os.path.isfile(file_path)

    with open(file_path, mode='a', newline='') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow([
                "Timestamp", "Side", "Entry Price", "Exit Price", "Profit", "Outcome",
                "Strategy Mode", "Zone Type", "Entry Reason", "SL", "TP", "Entry Time", "Exit Time"
            ])

        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            side,
            round(entry_price, 2),
            round(exit_price, 2),
            round(profit, 2),
            outcome,
            strategy_mode,
            zone_type or "-",
            entry_reason or "-",
            round(sl, 2) if sl else "-",
            round(tp, 2) if tp else "-",
            entry_time.strftime("%Y-%m-%d %H:%M:%S") if entry_time else "-",
            exit_time.strftime("%Y-%m-%d %H:%M:%S") if exit_time else "-"
        ])

def get_live_stats():
    if not os.path.isfile(file_path):
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "last_trade": None
        }

    with open(file_path, mode='r') as file:
        reader = csv.DictReader(file)
        trades = list(reader)

    total_trades = len(trades)
    wins = sum(1 for t in trades if t["Outcome"].lower() == "win")
    losses = sum(1 for t in trades if t["Outcome"].lower() == "loss")
    total_profit = sum(float(t["Profit"]) for t in trades if t["Profit"] not in ["", "-"])

    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    last_trade = trades[-1] if trades else None

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 2),
        "total_profit": round(total_profit, 2),
        "last_trade": last_trade
    }

def init_log():
    """Create the journal file with headers if it doesn't exist."""
    if not os.path.exists(file_path):
        with open(file_path, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([
                "Timestamp", "Side", "Entry Price", "Exit Price", "Profit", "Outcome",
                "Strategy Mode", "Zone Type", "Entry Reason", "SL", "TP", "Entry Time", "Exit Time"
            ])
        print("[Init Log] Created new journal file.")
    else:
        print("[Init Log] Journal already exists.")

def send_daily_summary():
    """Send a performance summary for trades made today."""
    if not os.path.isfile(file_path):
        send_telegram_message("📉 No trade journal found. No summary available.")
        return

    today_str = date.today().strftime("%Y-%m-%d")

    with open(file_path, mode='r') as file:
        reader = csv.DictReader(file)
        trades_today = [t for t in reader if t["Timestamp"].startswith(today_str)]

    total = len(trades_today)
    wins = sum(1 for t in trades_today if t["Outcome"].lower() == "win")
    losses = sum(1 for t in trades_today if t["Outcome"].lower() == "loss")
    profit = sum(float(t["Profit"]) for t in trades_today if t["Profit"] not in ["", "-"])

    win_rate = (wins / total * 100) if total else 0

    msg = (
        f"📊 *Daily Trade Summary* ({today_str}):\n\n"
        f"🔁 Total Trades: {total}\n"
        f"✅ Wins: {wins}\n"
        f"❌ Losses: {losses}\n"
        f"🎯 Win Rate: {win_rate:.2f}%\n"
        f"💰 Net Profit: ${profit:.2f}"
    )

    send_telegram_message(msg)
