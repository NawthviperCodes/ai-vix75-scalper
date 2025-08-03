# telegram_notifier.py

import requests
import time
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Rate limiting variables
_last_message_time = 0
_message_delay = 2  # Minimum seconds between messages
_message_queue = []
_last_flush_time = 0

def _send_telegram_message_now(message):
    """Internal function to actually send the message"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 429:
            retry_after = response.json().get('parameters', {}).get('retry_after', 5)
            print(f"[Telegram RATE LIMITED] Waiting {retry_after} seconds")
            time.sleep(retry_after)
            return _send_telegram_message_now(message)
        elif response.status_code != 200:
            print(f"[Telegram ERROR] {response.text}")
            return False
        return True
    except Exception as e:
        print(f"[Telegram ERROR] {e}")
        return False

def flush_message_queue():
    """Send all queued messages as a single message"""
    global _message_queue, _last_flush_time
    if not _message_queue:
        return
    
    current_time = time.time()
    if current_time - _last_flush_time < _message_delay:
        return
    
    combined_message = "\n".join(_message_queue)
    if _send_telegram_message_now(combined_message):
        _message_queue = []
        _last_flush_time = current_time

def send_telegram_message(message, priority="normal"):
    """
    Send message with rate limiting
    Priority can be "high", "normal", or "low"
    """
    global _last_message_time, _message_queue
    
    current_time = time.time()
    
    # High priority messages go immediately
    if priority == "high":
        # Wait if needed to respect rate limits
        time_since_last = current_time - _last_message_time
        if time_since_last < _message_delay:
            time.sleep(_message_delay - time_since_last)
        
        if _send_telegram_message_now(message):
            _last_message_time = time.time()
        return
    
    # Normal and low priority messages get queued
    _message_queue.append(message)
    
    # Flush queue if it's getting big or it's been a while
    if len(_message_queue) >= 3 or (current_time - _last_flush_time) > 30:
        flush_message_queue()