"""ПП.11, этап 3. Модульные тесты пересылки брони в ВК (VK API заменён заглушкой)."""
import json
import os
import sys
import tempfile
import unittest

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module   # noqa: E402
import db                  # noqa: E402
import vk                  # noqa: E402
import vk_bot              # noqa: E402

TOKEN = "fake-token-for-tests"
BOOKING = {"id": 17, "date": "2026-11-20", "start": "19:00", "end": "21:00", "guests": 4,
           "status": "new", "created_at": "2026-11-19T12:00:00",
           "guest": {"name": "Иванов Иван", "phone": "+79001234567", "email": None},
           "table": {"id": 3, "number": 3, "capacity": 4, "hall": "Основной"}}


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


class FakeSession:
    """Заглушка requests.Session: отдаёт заранее заданные ответы и запоминает запросы."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, dict(data)))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return FakeResponse(a)


def make_api(*answers):
    session = FakeSession(*answers)
    return vk.VkApi(TOKEN, session=session, sleep=lambda s: None), session


class FakeApi:
    """Заглушка VkApi для бота: записывает вызовы методов."""

    def __init__(self):
        self.calls = []

    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "users.get":
            return [{"first_name": "Пётр", "last_name": "Петров"}]
        return 1


class FormatTests(unittest.TestCase):
    def test_message_text(self):
        self.assertEqual(vk.format_booking(BOOKING),
                         "🆕 Новая бронь №17\nГость: Иванов Иван, +79001234567\n"
                         "Дата: 20.11.2026, 19:00–21:00\nЗал: Основной, столик №3 (4 места)\n"
                         "Гостей: 4\nСтатус: новая")

    def test_message_with_email_and_prefix(self):
        b = dict(BOOKING, guest=dict(BOOKING["guest"], email="ivan@example.com"))
        text = vk.format_booking(b, "ТЕСТ: ")
        self.assertTrue(text.startswith("ТЕСТ: 🆕 Новая бронь №17"))
        self.assertIn("Email: ivan@example.com", text)

    def test_seats_word(self):
        self.assertEqual([vk.seats(n) for n in (1, 2, 5, 11, 22)],
                         ["1 место", "2 места", "5 мест", "11 мест", "22 места"])

    def test_keyboard(self):
        kb = json.loads(vk.booking_keyboard(17))
        self.assertTrue(kb["inline"])
        confirm, reject = kb["buttons"][0]
        self.assertEqual(confirm["action"]["type"], "callback")
        self.assertEqual(confirm["action"]["label"], "Подтвердить")
        self.assertEqual(json.loads(confirm["action"]["payload"]), {"action": "confirm", "booking_id": 17})
        self.assertEqual(reject["color"], "negative")
        self.assertEqual(json.loads(reject["action"]["payload"])["action"], "reject")


class ApiTests(unittest.TestCase):
    def test_send_params(self):
        api, session = make_api({"response": 555})
        mid = vk.VkNotifier(api, 2000000001).send_booking(BOOKING)
        self.assertEqual(mid, 555)
        url, data = session.calls[0]
        self.assertEqual(url, "https://api.vk.ru/method/messages.send")
        self.assertEqual(data["peer_id"], 2000000001)
        self.assertEqual(data["v"], "5.199")
        self.assertIsInstance(data["random_id"], int)
        self.assertIn("Новая бронь №17", data["message"])
        self.assertIn("keyboard", data)

    def test_token_not_in_url_or_repr(self):
        api, session = make_api({"response": 1})
        api.call("messages.send", peer_id=1, random_id=1, message="x")
        self.assertNotIn(TOKEN, session.calls[0][0])
        self.assertNotIn(TOKEN, repr(api))

    def test_retry_keeps_random_id(self):
        api, session = make_api({"error": {"error_code": 10, "error_msg": "Internal server error"}},
                                requests.ConnectionError("нет сети"),
                                {"response": 77})
        self.assertEqual(vk.VkNotifier(api, 2000000001).send_booking(BOOKING), 77)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(len({c[1]["random_id"] for c in session.calls}), 1)

    def test_no_retry_on_auth_error(self):
        api, session = make_api({"error": {"error_code": 5, "error_msg": "User authorization failed"}})
        with self.assertRaises(vk.VkError) as ctx:
            api.call("messages.send", peer_id=1, random_id=1, message="x")
        self.assertEqual(ctx.exception.code, 5)
        self.assertEqual(len(session.calls), 1)

    def test_gives_up_after_attempts(self):
        api, session = make_api(*[{"error": {"error_code": 9, "error_msg": "Flood control"}}] * 3)
        with self.assertRaises(vk.VkError):
            api.call("messages.send", peer_id=1, random_id=1, message="x")
        self.assertEqual(len(session.calls), 3)

    def test_from_env(self):
        self.assertIsNone(vk.VkNotifier.from_env({}))
        n = vk.VkNotifier.from_env({"VK_TOKEN": TOKEN, "VK_PEER_ID": "2000000001"})
        self.assertEqual(n.peer_id, 2000000001)

    def test_empty_token(self):
        with self.assertRaises(ValueError):
            vk.VkApi("")


class RecordingNotifier:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send_booking(self, booking):
        self.sent.append(booking)
        if self.fail:
            raise vk.VkError(10, "Internal server error")
        return 100 + booking["id"]


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, notifier):
        return app_module.create_app(self.db_path, notifier=notifier).test_client()

    def book(self, client, **kw):
        data = dict(name="Иванов Иван", phone="+79001234567", table_id=3, date="2026-11-20",
                    start="19:00", end="21:00", guests=4, **kw)
        return client.post("/api/bookings", json=data)

    def test_new_booking_is_sent(self):
        n = RecordingNotifier()
        r = self.book(self.client(n))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(n.sent), 1)
        self.assertEqual(n.sent[0]["id"], r.get_json()["id"])
        self.assertEqual(n.sent[0]["table"]["number"], 3)

    def test_rejected_booking_not_sent(self):
        n = RecordingNotifier()
        c = self.client(n)
        self.book(c)
        r = self.book(c, )                      # тот же столик и время — 409
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(n.sent), 1)

    def test_vk_error_keeps_booking(self):
        c = self.client(RecordingNotifier(fail=True))
        with self.assertLogs("app", "ERROR"):
            r = self.book(c)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(c.get(f"/api/bookings/{r.get_json()['id']}").get_json()["status"], "new")

    def test_tables_and_form(self):
        c = self.client(RecordingNotifier())
        self.assertEqual(len(c.get("/api/tables?hall_id=1").get_json()), 7)
        self.assertEqual(len(c.get("/api/tables").get_json()), 9)
        page = c.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Бронирование столиков", page.get_data(as_text=True))
        page.close()


class BotTests(unittest.TestCase):
    PEER = 2000000001

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite")
        c = app_module.create_app(self.db_path, notifier=RecordingNotifier()).test_client()
        self.booking_id = c.post("/api/bookings", json=dict(
            name="Иванов Иван", phone="+79001234567", table_id=3, date="2026-11-20",
            start="19:00", end="21:00", guests=4)).get_json()["id"]
        self.api = FakeApi()
        self.bot = vk_bot.BookingBot(self.api, self.db_path, self.PEER)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, action, peer=PEER, booking_id=None):
        return {"user_id": 42, "peer_id": peer, "event_id": "ev1", "conversation_message_id": 5,
                "payload": {"action": action, "booking_id": booking_id or self.booking_id}}

    def status(self):
        conn = db.connect(self.db_path)
        try:
            return db.get_booking(conn, self.booking_id)["status"]
        finally:
            conn.close()

    def methods(self):
        return [m for m, _ in self.api.calls]

    def test_confirm(self):
        self.bot.handle_event(self.event("confirm"))
        self.assertEqual(self.status(), "confirmed")
        self.assertEqual(self.methods(), ["users.get", "messages.edit", "messages.sendMessageEventAnswer"])
        edit = self.api.calls[1][1]
        self.assertEqual(edit["conversation_message_id"], 5)
        self.assertIn("✅ Подтверждено: Пётр Петров", edit["message"])
        self.assertIn("Статус: подтверждена", edit["message"])
        self.assertEqual(json.loads(edit["keyboard"])["buttons"], [])

    def test_reject_frees_table(self):
        self.bot.handle_event(self.event("reject"))
        self.assertEqual(self.status(), "rejected")
        c = app_module.create_app(self.db_path, notifier=RecordingNotifier()).test_client()
        free = c.get("/api/tables/free?date=2026-11-20&start=19:00&end=21:00&guests=4").get_json()
        self.assertIn(3, [t["id"] for t in free])

    def test_second_press_does_not_change(self):
        self.bot.handle_event(self.event("confirm"))
        self.api.calls.clear()
        result = self.bot.handle_event(self.event("reject"))
        self.assertEqual(self.status(), "confirmed")
        self.assertEqual(result, "бронь уже подтверждена")
        self.assertEqual(self.methods(), ["messages.sendMessageEventAnswer"])

    def test_other_chat_ignored(self):
        self.assertEqual(self.bot.handle_event(self.event("confirm", peer=2000000099)),
                         "чужая беседа, пропуск")
        self.assertEqual(self.status(), "new")
        self.assertEqual(self.api.calls, [])

    def test_unknown_booking_and_button(self):
        self.assertEqual(self.bot.handle_event(self.event("confirm", booking_id=999)), "бронь не найдена")
        self.assertEqual(self.bot.handle_event(self.event("delete")), "неизвестная кнопка")
        self.assertEqual(self.status(), "new")

    def test_payload_as_string(self):
        ev = self.event("confirm")
        ev["payload"] = json.dumps(ev["payload"])
        self.bot.handle_event(ev)
        self.assertEqual(self.status(), "confirmed")

    def test_long_poll_loop(self):
        """Цикл Long Poll: получение сервера, событие message_event, обновление ts."""
        api = FakeApi()
        api.call = lambda method, **p: (api.calls.append((method, p)) or
                                        ({"server": "https://lp.vk.test", "key": "k", "ts": "1"}
                                         if method == "groups.getLongPollServer" else
                                         [{"first_name": "Пётр", "last_name": "Петров"}]
                                         if method == "users.get" else 1))
        bot = vk_bot.BookingBot(api, self.db_path, self.PEER)
        press = self.event("confirm")

        class LpSession:
            def __init__(self):
                self.requests = []

            def get(self, url, params=None, timeout=None):
                self.requests.append(dict(params))
                return FakeResponse({"ts": "2", "updates": [
                    {"type": "message_new", "object": {}},
                    {"type": "message_event", "object": press}]})

        lp = LpSession()
        bot.run(230000000, session=lp, stop=lambda: len(lp.requests) >= 1)
        self.assertEqual(lp.requests[0]["act"], "a_check")
        self.assertEqual(self.status(), "confirmed")


if __name__ == "__main__":
    unittest.main()
