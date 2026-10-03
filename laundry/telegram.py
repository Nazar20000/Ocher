import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)
_polling_started = False


def telegram_api(method, payload):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return None
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        logger.exception("Telegram API %s не ответил", method)
        return None


def connect_url(resident):
    username = settings.TELEGRAM_BOT_USERNAME
    if not username or not settings.TELEGRAM_BOT_TOKEN:
        return ""
    if not resident.telegram_link_code:
        resident.save()
    return f"https://t.me/{username}?start={resident.telegram_link_code}"


def send_telegram(chat_id, text):
    if not settings.TELEGRAM_BOT_TOKEN or not chat_id:
        return None
    return telegram_api(
        "sendMessage",
        {"chat_id": chat_id, "text": text},
    )


def handle_update(update):
    from .models import Resident

    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            send_telegram(
                chat_id,
                "Откройте страницу «Уведомления» на сайте очереди и нажмите «Открыть Telegram».",
            )
            return
        resident = Resident.objects.filter(telegram_link_code=code).first()
        if resident is None:
            send_telegram(chat_id, "Ссылка устарела. Откройте «Уведомления» на сайте и подключите бота снова.")
            return
        Resident.objects.filter(telegram_chat_id=str(chat_id)).exclude(pk=resident.pk).update(telegram_chat_id="")
        resident.telegram_chat_id = str(chat_id)
        resident.save(update_fields=["telegram_chat_id"])
        send_telegram(
            chat_id,
            f"{resident.name}, Telegram подключён. Сюда придёт сообщение, когда подойдёт ваша очередь.",
        )
        return

    if text.startswith("/stop"):
        updated = Resident.objects.filter(telegram_chat_id=str(chat_id)).update(telegram_chat_id="")
        if updated:
            send_telegram(chat_id, "Уведомления в Telegram отключены.")
        else:
            send_telegram(chat_id, "Этот чат не был подключён к очереди.")


def start_polling():
    global _polling_started
    if _polling_started or not settings.TELEGRAM_BOT_TOKEN:
        return
    _polling_started = True
    threading.Thread(target=_poll_loop, name="telegram-poll", daemon=True).start()


def _poll_loop():
    import time

    telegram_api("deleteWebhook", {"drop_pending_updates": False})
    offset = None
    while True:
        close_old_connections()
        payload = {"timeout": 20}
        if offset is not None:
            payload["offset"] = offset
        data = telegram_api("getUpdates", payload)
        results = (data or {}).get("result") or []
        if data is None:
            time.sleep(5)
            continue
        for update in results:
            offset = update["update_id"] + 1
            try:
                handle_update(update)
            except Exception:
                logger.exception("Не удалось обработать сообщение Telegram")
