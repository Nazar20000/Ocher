from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Machine, QueueEntry

OPEN_STATUSES = [QueueEntry.Status.ACTIVE, QueueEntry.Status.WAITING]


class QueueError(Exception):
    pass


def ensure_machines():
    for number in (1, 2, 3):
        Machine.objects.get_or_create(
            number=number,
            defaults={"title": f"Стиралка {number}"},
        )


def get_board(resident):
    if Machine.objects.count() < 3:
        ensure_machines()

    machines = list(Machine.objects.order_by("number"))
    entries = QueueEntry.objects.filter(
        machine__in=machines,
        status__in=OPEN_STATUSES,
    ).select_related("resident", "machine")

    grouped = {machine.id: [] for machine in machines}
    for entry in entries:
        grouped[entry.machine_id].append(entry)

    for machine in machines:
        rows = grouped[machine.id]
        rows.sort(
            key=lambda entry: (
                0 if entry.status == QueueEntry.Status.ACTIVE else 1,
                entry.created_at,
                entry.id,
            )
        )
        if rows and rows[0].status != QueueEntry.Status.ACTIVE:
            first = rows[0]
            now = timezone.now()
            QueueEntry.objects.filter(
                pk=first.pk,
                status=QueueEntry.Status.WAITING,
            ).update(status=QueueEntry.Status.ACTIVE, started_at=now)
            first.status = QueueEntry.Status.ACTIVE
            first.started_at = now

        machine.queue = rows
        machine.current = rows[0] if rows else None
        machine.your_entry = None
        machine.your_position = None
        for index, entry in enumerate(rows, start=1):
            if entry.resident_id == resident.id:
                machine.your_entry = entry
                machine.your_position = index
                break

    return machines


def _open_entry(resident):
    return (
        QueueEntry.objects.filter(resident=resident, status__in=OPEN_STATUSES)
        .select_related("machine")
        .first()
    )


@transaction.atomic
def join_queue(machine, resident):
    existing = _open_entry(resident)
    if existing:
        if existing.machine_id == machine.id:
            raise QueueError("Вы уже стоите в очереди к этой стиралке.")
        raise QueueError(f"Сначала завершите очередь к «{existing.machine.title}».")

    has_active = QueueEntry.objects.filter(
        machine=machine,
        status=QueueEntry.Status.ACTIVE,
    ).exists()
    now = timezone.now()
    status = QueueEntry.Status.WAITING if has_active else QueueEntry.Status.ACTIVE
    try:
        with transaction.atomic():
            entry = QueueEntry.objects.create(
                machine=machine,
                resident=resident,
                status=status,
                started_at=None if has_active else now,
            )
        _remember_join(entry)
        return entry
    except IntegrityError:
        existing = _open_entry(resident)
        if existing:
            if existing.machine_id == machine.id:
                raise QueueError("Вы уже стоите в очереди к этой стиралке.")
            raise QueueError(f"Сначала завершите очередь к «{existing.machine.title}».")
        entry = QueueEntry.objects.create(
            machine=machine,
            resident=resident,
            status=QueueEntry.Status.WAITING,
        )
        _remember_join(entry)
        return entry


def _remember_join(entry):
    from .notify import schedule_joined

    schedule_joined(entry.id)


@transaction.atomic
def complete_turn(entry_id, resident):
    entry = (
        QueueEntry.objects.select_related("machine", "resident")
        .filter(pk=entry_id)
        .first()
    )
    if entry is None:
        raise QueueError("Запись очереди не найдена.")
    if entry.resident_id != resident.id:
        raise QueueError("Завершить можно только свою очередь.")
    if entry.status != QueueEntry.Status.ACTIVE:
        raise QueueError("Сейчас не ваша очередь.")

    updated = QueueEntry.objects.filter(
        pk=entry.pk,
        resident=resident,
        status=QueueEntry.Status.ACTIVE,
    ).update(status=QueueEntry.Status.DONE, finished_at=timezone.now())
    if updated != 1:
        raise QueueError("Очередь уже обновлена. Обновите страницу.")

    nxt = _promote_next(entry.machine_id)
    _remember_queue_change(entry, nxt)
    return nxt


def _promote_next(machine_id):
    nxt = (
        QueueEntry.objects.filter(
            machine_id=machine_id,
            status=QueueEntry.Status.WAITING,
        )
        .order_by("created_at", "id")
        .first()
    )
    if nxt is None:
        return None
    promoted = QueueEntry.objects.filter(
        pk=nxt.pk,
        status=QueueEntry.Status.WAITING,
    ).update(status=QueueEntry.Status.ACTIVE, started_at=timezone.now())
    if promoted != 1:
        return None
    return (
        QueueEntry.objects.select_related("resident", "machine")
        .filter(pk=nxt.pk)
        .first()
    )


def _remember_queue_change(entry, nxt):
    from .notify import schedule_queue_update

    schedule_queue_update(
        entry.machine_id,
        entry.created_at,
        entry.id,
        nxt.id if nxt else None,
    )


@transaction.atomic
def leave_queue(entry_id, resident):
    entry = QueueEntry.objects.select_related("machine").filter(pk=entry_id).first()
    if entry is None:
        raise QueueError("Запись очереди не найдена.")
    if entry.resident_id != resident.id:
        raise QueueError("Отменить можно только свою очередь.")
    if entry.status not in OPEN_STATUSES:
        raise QueueError("Эту очередь уже нельзя отменить.")

    was_active = entry.status == QueueEntry.Status.ACTIVE
    updated = QueueEntry.objects.filter(
        pk=entry.pk,
        resident=resident,
        status__in=OPEN_STATUSES,
    ).update(status=QueueEntry.Status.LEFT, finished_at=timezone.now())
    if updated != 1:
        raise QueueError("Очередь уже обновлена. Обновите страницу.")

    nxt = _promote_next(entry.machine_id) if was_active else None
    _remember_queue_change(entry, nxt)
    return nxt
