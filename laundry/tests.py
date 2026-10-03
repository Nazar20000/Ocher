from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from .models import Machine, QueueEntry, Resident
from .phones import normalize_phone
from .services import QueueError, complete_turn, ensure_machines, get_board, join_queue, leave_queue
from .telegram import handle_update


class PhoneTests(TestCase):
    def test_tajik_local_and_full(self):
        self.assertEqual(normalize_phone("90 111 22 33"), "992901112233")
        self.assertEqual(normalize_phone("+992 90 111 22 33"), "992901112233")

    def test_russian_numbers(self):
        self.assertEqual(normalize_phone("+7 900 123-45-67"), "79001234567")
        self.assertEqual(normalize_phone("8 900 123 45 67"), "79001234567")

    def test_rejects_short_number(self):
        with self.assertRaises(ValidationError):
            normalize_phone("12345")


class QueueFlowTests(TestCase):
    def setUp(self):
        ensure_machines()
        self.machine = Machine.objects.get(number=1)
        self.other = Machine.objects.get(number=2)
        self.ali = Resident.objects.create(name="Али", apartment="12", phone="992901112233")
        self.behruz = Resident.objects.create(name="Бехруз", apartment="15", phone="992902223344")
        self.madina = Resident.objects.create(name="Мадина", apartment="18", phone="992903334455")

    def test_join_empty_makes_resident_active(self):
        entry = join_queue(self.machine, self.ali)
        self.assertEqual(entry.status, QueueEntry.Status.ACTIVE)
        self.assertIsNotNone(entry.started_at)

    def test_next_residents_wait_until_complete(self):
        join_queue(self.machine, self.ali)
        second = join_queue(self.machine, self.behruz)
        third = join_queue(self.machine, self.madina)
        self.assertEqual(second.status, QueueEntry.Status.WAITING)
        self.assertEqual(third.status, QueueEntry.Status.WAITING)

        promoted = complete_turn(QueueEntry.objects.get(resident=self.ali).id, self.ali)
        self.assertEqual(promoted.resident, self.behruz)
        self.assertEqual(promoted.status, QueueEntry.Status.ACTIVE)
        third.refresh_from_db()
        self.assertEqual(third.status, QueueEntry.Status.WAITING)

        promoted = complete_turn(promoted.id, self.behruz)
        self.assertEqual(promoted.resident, self.madina)

    def test_last_completion_frees_machine(self):
        entry = join_queue(self.machine, self.ali)
        self.assertIsNone(complete_turn(entry.id, self.ali))
        self.assertFalse(
            QueueEntry.objects.filter(
                machine=self.machine,
                status__in=[QueueEntry.Status.ACTIVE, QueueEntry.Status.WAITING],
            ).exists()
        )

    def test_cannot_complete_someone_else(self):
        entry = join_queue(self.machine, self.ali)
        with self.assertRaises(QueueError):
            complete_turn(entry.id, self.behruz)

    def test_cannot_join_two_machines(self):
        join_queue(self.machine, self.ali)
        with self.assertRaises(QueueError):
            join_queue(self.other, self.ali)

    def test_waiting_resident_can_leave_without_skipping_order(self):
        join_queue(self.machine, self.ali)
        second = join_queue(self.machine, self.behruz)
        third = join_queue(self.machine, self.madina)
        leave_queue(second.id, self.behruz)
        second.refresh_from_db()
        self.assertEqual(second.status, QueueEntry.Status.LEFT)

        promoted = complete_turn(QueueEntry.objects.get(resident=self.ali).id, self.ali)
        self.assertEqual(promoted.resident, self.madina)
        third.refresh_from_db()
        self.assertEqual(third.status, QueueEntry.Status.ACTIVE)

    def test_active_resident_can_cancel_and_pass_the_turn(self):
        join_queue(self.machine, self.ali)
        second = join_queue(self.machine, self.behruz)
        promoted = leave_queue(QueueEntry.objects.get(resident=self.ali).id, self.ali)
        self.assertEqual(promoted.resident, self.behruz)
        second.refresh_from_db()
        self.assertEqual(second.status, QueueEntry.Status.ACTIVE)
        ali_entry = QueueEntry.objects.get(resident=self.ali)
        self.assertEqual(ali_entry.status, QueueEntry.Status.LEFT)

    def test_cannot_cancel_someone_else(self):
        entry = join_queue(self.machine, self.ali)
        with self.assertRaises(QueueError):
            leave_queue(entry.id, self.behruz)

    def test_cancel_notifies_the_next_resident_by_email(self):
        self.behruz.email = "behruz@example.com"
        self.behruz.save()
        join_queue(self.machine, self.ali)
        join_queue(self.machine, self.behruz)
        with self.captureOnCommitCallbacks(execute=True):
            leave_queue(QueueEntry.objects.get(resident=self.ali).id, self.ali)
        self.assertTrue(any(item.subject == "Сейчас ваша очередь" and item.to == ["behruz@example.com"] for item in mail.outbox))

    def test_board_promotes_waiting_resident_if_nobody_is_active(self):
        QueueEntry.objects.create(
            machine=self.machine,
            resident=self.ali,
            status=QueueEntry.Status.WAITING,
        )
        board = get_board(self.ali)
        machine = next(item for item in board if item.number == 1)
        self.assertEqual(machine.current.resident, self.ali)
        self.assertEqual(machine.current.status, QueueEntry.Status.ACTIVE)
        self.assertEqual(machine.your_position, 1)


class PageTests(TestCase):
    def setUp(self):
        ensure_machines()

    def test_home_requires_login(self):
        response = Client().get("/")
        self.assertRedirects(response, "/login/")

    def test_register_login_join_and_complete(self):
        ali = Client()
        response = ali.post(
            "/register/",
            {"name": "Али", "apartment": "12", "phone": "+992 90 111 22 33"},
        )
        self.assertRedirects(response, "/")
        home = ali.get("/")
        self.assertContains(home, "Стиралка 1")
        self.assertContains(home, "Стиралка 2")
        self.assertContains(home, "Стиралка 3")

        joined = ali.post("/m/1/join/")
        self.assertRedirects(joined, "/m/1/")
        page = ali.get("/m/1/")
        self.assertContains(page, "Сейчас ваша очередь")
        self.assertContains(page, "Я забрал бельё")
        self.assertContains(page, "Отменить очередь")

        behruz = Client()
        behruz.post(
            "/register/",
            {"name": "Бехруз", "apartment": "15", "phone": "902223344"},
        )
        behruz.post("/m/1/join/")
        waiting = behruz.get("/m/1/")
        self.assertContains(waiting, "Вы №2 в очереди")
        self.assertContains(waiting, "Али")

        entry = QueueEntry.objects.get(resident__name="Али")
        done = ali.post(f"/queue/{entry.id}/complete/")
        self.assertRedirects(done, "/m/1/")
        self.assertContains(ali.get("/m/1/"), "Бехруз")

        again = behruz.get("/m/1/")
        self.assertContains(again, "Сейчас ваша очередь")

    def test_login_with_same_phone(self):
        client = Client()
        client.post(
            "/register/",
            {"name": "Мадина", "apartment": "18", "phone": "+992901113344"},
        )
        client.post("/logout/")
        response = client.post("/login/", {"phone": "90 111 33 44"})
        self.assertRedirects(response, "/")
        self.assertContains(client.get("/"), "Мадина")


class NotificationTests(TestCase):
    def test_profile_saves_email(self):
        client = Client()
        client.post("/register/", {"name": "Али", "apartment": "12", "phone": "+992 90 111 22 33"})
        response = client.post("/profile/", {"email": "ali@example.com"})
        self.assertRedirects(response, "/profile/")
        resident = Resident.objects.get()
        self.assertEqual(resident.email, "ali@example.com")
        page = client.get("/profile/")
        self.assertContains(page, "ali@example.com")
        self.assertEqual(mail.outbox[0].subject, "Почта подключена")

    def test_telegram_start_links_chat(self):
        resident = Resident.objects.create(name="Али", apartment="12", phone="992901112233")
        resident.telegram_link_code = "linkcode1"
        resident.save(update_fields=["telegram_link_code"])
        handle_update({"message": {"text": "/start linkcode1", "chat": {"id": 555}}})
        resident.refresh_from_db()
        self.assertEqual(resident.telegram_chat_id, "555")

    @override_settings(TELEGRAM_WEBHOOK_SECRET="secret")
    def test_webhook_rejects_wrong_secret(self):
        response = Client().post(
            "/telegram/webhook/wrong/",
            data="{}",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
