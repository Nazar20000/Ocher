from django.contrib import admin

from .models import Machine, QueueEntry, Resident


@admin.register(Resident)
class ResidentAdmin(admin.ModelAdmin):
    list_display = ("name", "apartment", "phone", "email", "telegram_chat_id", "created_at")
    search_fields = ("name", "apartment", "phone", "email")


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ("number", "title")


@admin.register(QueueEntry)
class QueueEntryAdmin(admin.ModelAdmin):
    list_display = ("machine", "resident", "status", "created_at", "started_at", "finished_at")
    list_filter = ("status", "machine")
    search_fields = ("resident__name", "resident__apartment", "resident__phone")
