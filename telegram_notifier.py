# telegram_notifier.py

import requests

from dotenv import load_dotenv
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHAT_ID = os.getenv("CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"[Telegram ERROR] {response.text}")
        else:
            print("[Telegram] Message sent.")
    except Exception as e:
        print(f"[Telegram ERROR] {e}")