"""One-time: after you message your bot, this finds your chat id, saves it to .env and sends a test.
PYTHONPATH=src python -m fxengine.live.telegram_setup"""
import requests
from pathlib import Path
from ..envfile import load_env
from .telegram import send


def main():
    env = load_env()
    tok = env.get("TELEGRAM_TOKEN")
    if not tok:
        raise SystemExit("TELEGRAM_TOKEN missing from .env")
    r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
    chats = [u["message"]["chat"]["id"] for u in r.get("result", []) if "message" in u]
    if not chats:
        raise SystemExit("No messages found. Open your bot in Telegram, press Start, send 'hi', then run this again.")
    chat = chats[-1]
    p = Path(".env")
    lines = [l for l in p.read_text().splitlines() if not l.startswith("TELEGRAM_CHAT_ID=")]
    p.write_text("\n".join(lines + [f"TELEGRAM_CHAT_ID={chat}"]) + "\n")
    env["TELEGRAM_CHAT_ID"] = str(chat)
    print("Test message sent:", send(env, "✅ FX Engine connected. Alerts will arrive here. Research only: no orders are ever placed."))


if __name__ == "__main__":
    main()
