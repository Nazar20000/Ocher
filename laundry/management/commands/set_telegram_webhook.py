from django.conf import settings
from django.core.management.base import BaseCommand

from laundry.telegram import telegram_api


class Command(BaseCommand):
    help = "Включает webhook Telegram на домене сайта."

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_WEBHOOK_SECRET:
            self.stderr.write("Заполните TELEGRAM_BOT_TOKEN и TELEGRAM_WEBHOOK_SECRET в .env.")
            return
        url = f"{settings.SITE_URL}/telegram/webhook/{settings.TELEGRAM_WEBHOOK_SECRET}/"
        result = telegram_api("setWebhook", {"url": url})
        self.stdout.write(url)
        self.stdout.write(str(result))
