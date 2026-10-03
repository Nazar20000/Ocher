import os

from django.apps import AppConfig


class LaundryConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "laundry"
    verbose_name = "Очередь"

    def ready(self):
        from django.conf import settings
        from django.db.models.signals import post_migrate

        post_migrate.connect(seed_machines, sender=self)
        if os.environ.get("RUN_MAIN") == "true" and settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_USE_POLLING:
            from .telegram import start_polling

            start_polling()


def seed_machines(sender, **kwargs):
    from .models import Machine

    for number in (1, 2, 3):
        Machine.objects.get_or_create(
            number=number,
            defaults={"title": f"Стиралка {number}"},
        )
