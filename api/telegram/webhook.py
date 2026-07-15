"""POST /api/telegram/webhook"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import json
from lib.response import json_response, error

WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

def handler(request, response):
    if request.method != "POST":
        return error("Method not allowed", 405)

    # Verifikasi secret token dari Telegram
    if WEBHOOK_SECRET:
        got_secret = request.headers.get("x-telegram-bot-api-secret-token", "")
        if got_secret != WEBHOOK_SECRET:
            return error("Unauthorized", 403)

    try:
        update = json.loads(request.body)
    except Exception:
        return error("Invalid JSON", 400)

    # Import bot — lazy import agar tidak crash jika env belum tersedia
    try:
        # Bot ada di bot/bot.py relatif terhadap root vercel-version
        bot_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'bot')
        sys.path.insert(0, os.path.abspath(bot_dir))
        import bot as bot_module

        if "message" in update:
            bot_module.handle_message(update["message"])
        elif "callback_query" in update:
            bot_module.handle_callback(update["callback_query"])
    except Exception as e:
        print(f"[webhook] Bot error: {e}")
        # Jangan return error ke Telegram — Telegram akan retry terus
        # Cukup log dan balas 200 OK

    return json_response({"ok": True})
