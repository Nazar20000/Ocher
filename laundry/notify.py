import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import QueueEntry
from .telegram import send_telegram

logger = logging.getLogger(__name__)
OPEN = [QueueEntry.Status.ACTIVE, QueueEntry.Status.WAITING]


def send_notification(resident, subject, body):
    if resident.email:
        try:
            send_mail(
                subject,
                body,
                settings.DEFAULT_FROM_EMAIL,
                [resident.email],
                fail_silently=False,
            )
        except Exception:
            logger.exception("Не удалось отправить письмо жильцу %s", resident.pk)
    if resident.telegram_chat_id:
        send_telegram(resident.telegram_chat_id, f"{subject}\n\n{body}")


def notify_turn(entry):
    send_notification(
        entry.resident,
        "Сейчас ваша очередь",
        (
            f"{entry.machine.title} свободна для вас. "
            f"Когда заберёте бельё, отметьте это на сайте {settings.SITE_URL}."
        ),
    )


def notify_position(entry, position):
    send_notification(
        entry.resident,
        "Вы в очереди",
        f"{entry.machine.title}. Ваш номер: {position}. Сайт: {settings.SITE_URL}.",
    )


def schedule_joined(entry_id):
    def _run(entry_id=entry_id):
        entry = (
            QueueEntry.objects.select_related("resident", "machine")
            .filter(pk=entry_id, status__in=OPEN)
            .first()
        )
        if entry is None:
            return
        if entry.status == QueueEntry.Status.ACTIVE:
            notify_turn(entry)
            return
        position = (
            QueueEntry.objects.filter(
                machine_id=entry.machine_id,
                status__in=OPEN,
                created_at__lte=entry.created_at,
            )
            .exclude(created_at=entry.created_at, id__gt=entry.id)
            .count()
        )
        notify_position(entry, position)

    transaction.on_commit(_run)


def schedule_queue_update(machine_id, removed_created_at, removed_id, promoted_entry_id):
    def _run(
        machine_id=machine_id,
        removed_created_at=removed_created_at,
        removed_id=removed_id,
        promoted_entry_id=promoted_entry_id,
    ):
        entries = list(
            QueueEntry.objects.filter(machine_id=machine_id, status__in=OPEN)
            .select_related("resident", "machine")
            .order_by("created_at", "id")
        )
        for index, entry in enumerate(entries, start=1):
            if promoted_entry_id and entry.id == promoted_entry_id:
                notify_turn(entry)
                continue
            if (entry.created_at, entry.id) > (removed_created_at, removed_id) and entry.status == QueueEntry.Status.WAITING:
                notify_position(entry, index)

    transaction.on_commit(_run)
