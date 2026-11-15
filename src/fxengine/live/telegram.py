"""Telegram sender (HTTPS to api.telegram.org). Token/chat id come from .env only."""
import requests


def send(env: dict, text: str, timeout=15) -> bool:
    tok, chat = env.get("TELEGRAM_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def send_file(env: dict, path: str, caption="", timeout=30) -> bool:
    tok, chat = env.get("TELEGRAM_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    try:
        with open(path, "rb") as f:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendDocument", data={"chat_id": chat, "caption": caption},
                              files={"document": f}, timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False
