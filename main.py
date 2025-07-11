# === main.py ===
import MetaTrader5 as mt5
from scalper_strategy_engine import monitor_and_trade, SYMBOL, TIMEFRAME_ENTRY, notify_strategy_change
from emergency_control import check_emergency_stop
from performance_tracker import init_log, send_daily_summary
from symbol_info_helper import print_symbol_lot_info
from trade_executor import trail_sl as apply_trailing_stop
from datetime import datetime
from dotenv import load_dotenv
import time
import os

load_dotenv()

MT5_LOGIN = int(os.getenv("MT5_LOGIN"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")

SUMMARY_SENT = False
BOT_RUNNING = False


def run_bot(strategy_mode, lot_size):
    global SUMMARY_SENT, BOT_RUNNING
    BOT_RUNNING = True

    print("Connecting to MetaTrader 5...")
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        print("[ERROR] MT5 Initialization Failed!")
        return

    print_symbol_lot_info(SYMBOL)
    init_log()
    notify_strategy_change(strategy_mode)

    last_candle_time = None
    print(f"[OK] Bot started in '{strategy_mode}' mode with lot size {lot_size}...\n")

    try:
        while BOT_RUNNING:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                time.sleep(0.1)
                continue

            rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME_ENTRY, 0, 1)
            if not rates:
                time.sleep(0.1)
                continue

            current_candle_time = rates[0]['time']
            equity = mt5.account_info().equity

            if reason := check_emergency_stop(equity):
                from telegram_notifier import send_telegram_message
                send_telegram_message(f"\u274c Bot stopped: {reason}")
                mt5.shutdown()
                break

            if current_candle_time != last_candle_time:
                last_candle_time = current_candle_time

                try:
                    monitor_and_trade(strategy_mode=strategy_mode, fixed_lot=lot_size)
                except Exception as e:
                    print(f"[ERROR] Strategy engine failed: {e}")

                apply_trailing_stop(SYMBOL, magic=77775)

                now = datetime.now()
                if 23 <= now.hour < 24 and 58 <= now.minute <= 59 and not SUMMARY_SENT:
                    send_daily_summary()
                    SUMMARY_SENT = True

                if now.hour == 0 and now.minute == 0:
                    SUMMARY_SENT = False

            time.sleep(0.1)
    except Exception as e:
        print(f"[BOT ERROR] {e}")
    finally:
        mt5.shutdown()
        BOT_RUNNING = False


def stop_bot():
    global BOT_RUNNING
    BOT_RUNNING = False
