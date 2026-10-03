import secrets

from django.db import models
from django.db.models import Q


class Resident(models.Model):
    name = models.CharField("Имя", max_length=80)
    apartment = models.CharField("Квартира", max_length=20)
    phone = models.CharField("Телефон", max_length=20, unique=True)
    email = models.EmailField("Почта", blank=True, default="")
    telegram_chat_id = models.CharField("Telegram", max_length=32, blank=True, default="")
    telegram_link_code = models.CharField(max_length=32, blank=True, null=True, unique=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.telegram_link_code:
            self.telegram_link_code = secrets.token_urlsafe(12)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Жилец"
        verbose_name_plural = "Жильцы"
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=~Q(email=""),
                name="unique_resident_email",
            ),
        ]

    def __str__(self):
        return f"{self.name} (кв. {self.apartment})"


class Machine(models.Model):
    number = models.PositiveSmallIntegerField("Номер", unique=True)
    title = models.CharField("Название", max_length=40)

    class Meta:
        verbose_name = "Стиралка"
        verbose_name_plural = "Стиралки"
        ordering = ["number"]

    def __str__(self):
        return self.title


class QueueEntry(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Сейчас"
        WAITING = "waiting", "Ожидает"
        DONE = "done", "Завершена"
        LEFT = "left", "Вышел"

    machine = models.ForeignKey(
        Machine,
        verbose_name="Стиралка",
        related_name="entries",
        on_delete=models.CASCADE,
    )
    resident = models.ForeignKey(
        Resident,
        verbose_name="Жилец",
        related_name="entries",
        on_delete=models.CASCADE,
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.WAITING,
    )
    created_at = models.DateTimeField("Встал в очередь", auto_now_add=True)
    started_at = models.DateTimeField("Начал", null=True, blank=True)
    finished_at = models.DateTimeField("Закончил", null=True, blank=True)

    class Meta:
        verbose_name = "Запись очереди"
        verbose_name_plural = "Очередь"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["resident"],
                condition=Q(status__in=["active", "waiting"]),
                name="one_open_queue_per_resident",
            ),
            models.UniqueConstraint(
                fields=["machine"],
                condition=Q(status="active"),
                name="one_active_per_machine",
            ),
        ]
        indexes = [
            models.Index(fields=["machine", "status", "created_at"]),
        ]

    def __str__(self):
        return f"{self.machine} — {self.resident} ({self.get_status_display()})"
