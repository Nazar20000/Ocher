import json
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .forms import LoginForm, ProfileForm, RegisterForm
from .models import Machine, Resident
from .notify import send_notification
from .services import QueueError, complete_turn, get_board, join_queue, leave_queue
from .telegram import connect_url, handle_update


def _resident_from_session(request):
    resident_id = request.session.get("resident_id")
    if not resident_id:
        return None
    found = Resident.objects.filter(pk=resident_id).first()
    if found is None:
        request.session.pop("resident_id", None)
    return found


def resident_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        found = _resident_from_session(request)
        if found is None:
            return redirect("login")
        request.resident = found
        return view(request, *args, **kwargs)

    return wrapper


def _login(request, resident):
    request.session.cycle_key()
    request.session["resident_id"] = resident.id


@require_http_methods(["GET", "POST"])
def login_view(request):
    if _resident_from_session(request):
        return redirect("home")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        found = Resident.objects.filter(phone=form.cleaned_data["phone"]).first()
        if found is None:
            form.add_error("phone", "Номер не найден. Сначала зарегистрируйтесь.")
        else:
            _login(request, found)
            return redirect("home")
    return render(request, "laundry/login.html", {"form": form})


@require_http_methods(["GET", "POST"])
def register_view(request):
    if _resident_from_session(request):
        return redirect("home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            found = Resident.objects.create(
                name=form.cleaned_data["name"],
                apartment=form.cleaned_data["apartment"],
                phone=form.cleaned_data["phone"],
            )
        except IntegrityError:
            form.add_error("phone", "Этот номер уже зарегистрирован. Войдите.")
        else:
            _login(request, found)
            messages.success(request, "Вы зарегистрированы.")
            return redirect("home")
    return render(request, "laundry/register.html", {"form": form})


@require_POST
def logout_view(request):
    request.session.flush()
    return redirect("login")


@resident_required
def home(request):
    return render(
        request,
        "laundry/home.html",
        {"machines": get_board(request.resident)},
    )


@resident_required
def machine_detail(request, number):
    machines = get_board(request.resident)
    machine = next((item for item in machines if item.number == number), None)
    if machine is None:
        get_object_or_404(Machine, number=number)
    your_open = next((item.your_entry for item in machines if item.your_entry), None)
    return render(
        request,
        "laundry/machine.html",
        {"machine": machine, "your_open": your_open},
    )


@require_POST
@resident_required
def join(request, number):
    machine = get_object_or_404(Machine, number=number)
    try:
        entry = join_queue(machine, request.resident)
    except QueueError as exc:
        messages.error(request, str(exc))
    else:
        if entry.status == entry.Status.ACTIVE:
            messages.success(request, "Стиралка свободна — сейчас ваша очередь.")
        else:
            messages.success(request, "Вы встали в очередь.")
    return redirect("machine", number=number)


@require_POST
@resident_required
def complete(request, entry_id):
    try:
        nxt = complete_turn(entry_id, request.resident)
    except QueueError as exc:
        messages.error(request, str(exc))
        return redirect("home")
    if nxt is None:
        messages.success(request, "Стирка завершена. Стиралка свободна.")
    else:
        messages.success(
            request,
            f"Стирка завершена. Теперь очередь: {nxt.resident.name}, кв. {nxt.resident.apartment}.",
        )
    return redirect("machine", number=nxt.machine.number if nxt else _machine_number(entry_id))


def _machine_number(entry_id):
    from .models import QueueEntry

    entry = QueueEntry.objects.select_related("machine").filter(pk=entry_id).first()
    if entry is None:
        return 1
    return entry.machine.number


@require_POST
@resident_required
def leave(request, entry_id):
    from .models import QueueEntry

    entry = QueueEntry.objects.select_related("machine").filter(pk=entry_id).first()
    number = entry.machine.number if entry else 1
    try:
        nxt = leave_queue(entry_id, request.resident)
    except QueueError as exc:
        messages.error(request, str(exc))
    else:
        if nxt is None:
            messages.success(request, "Очередь отменена.")
        else:
            messages.success(
                request,
                f"Очередь отменена. Теперь стирает {nxt.resident.name}, кв. {nxt.resident.apartment}.",
            )
    return redirect("machine", number=number)


@resident_required
@require_http_methods(["GET", "POST"])
def profile(request):
    resident = request.resident
    form = ProfileForm(request.POST or None, resident=resident)
    if request.method == "POST" and form.is_valid():
        previous = resident.email
        resident.email = form.cleaned_data["email"]
        resident.save(update_fields=["email", "telegram_link_code"])
        if resident.email and resident.email != previous:
            send_notification(
                resident,
                "Почта подключена",
                f"Сюда будут приходить уведомления об очереди. Сайт: {settings.SITE_URL}.",
            )
        messages.success(request, "Настройки уведомлений сохранены.")
        return redirect("profile")
    return render(
        request,
        "laundry/profile.html",
        {
            "form": form,
            "telegram_url": connect_url(resident),
            "email_ready": bool(settings.EMAIL_HOST),
            "telegram_ready": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_USERNAME),
        },
    )


@require_POST
@resident_required
def telegram_disconnect(request):
    request.resident.telegram_chat_id = ""
    request.resident.save(update_fields=["telegram_chat_id"])
    messages.success(request, "Telegram отключён.")
    return redirect("profile")


@csrf_exempt
@require_POST
def telegram_webhook(request, secret):
    if not settings.TELEGRAM_WEBHOOK_SECRET or secret != settings.TELEGRAM_WEBHOOK_SECRET:
        return HttpResponse(status=404)
    try:
        update = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return HttpResponse(status=400)
    handle_update(update)
    return HttpResponse("ok")
