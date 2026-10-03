from django.core.management.base import BaseCommand

from laundry.telegram import _poll_loop


class Command(BaseCommand):
    help = "Слушает Telegram и подключает жильцов по ссылке с сайта."

    def handle(self, *args, **options):
        self.stdout.write("Слушаю Telegram. Остановка: Ctrl+C.")
        _poll_loop()
