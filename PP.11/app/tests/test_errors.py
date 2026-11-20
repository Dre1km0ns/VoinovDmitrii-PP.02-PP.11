"""ПП.11, этап 4. Обработка ошибок: ВКонтакте недоступен и неверные входные данные."""
import json
import logging
import socket
import threading
import time

import pytest
import requests

import app as app_module
import vk
import vk_bot
from tests.conftest import DAY, PEER, FakeResponse, booking_data

PAST = "2020-01-01"


# ---------- ВКонтакте недоступен ----------
class ScriptedSession:
    """Сессия, которая отдаёт заранее заданные ответы или исключения."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def post(self, url, data=None, timeout=None):
        self.calls += 1
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        return FakeResponse(a)


def make_client(db_path, session, attempts=3):
    api = vk.VkApi("fake-token-for-tests", session=session, attempts=attempts, sleep=lambda s: None)
    return app_module.create_app(db_path, notifier=vk.VkNotifier(api, PEER)).test_client()


def assert_saved_not_notified(client, r):
    assert r.status_code == 201
    b = r.get_json()
    assert b["notified"] is False
    saved = client.get(f"/api/bookings/{b['id']}").get_json()
    assert saved["status"] == "new"                       # бронь сохранена и ждёт решения
    return b


@pytest.mark.parametrize("answer, calls", [
    (requests.ConnectionError("нет сети"), 3),              # сеть недоступна — 3 попытки
    (requests.Timeout("тайм-аут"), 3),                      # ВК не отвечает — 3 попытки
    (ValueError("HTML вместо JSON"), 3),                    # ответ не JSON (502 от прокси)
    ({"unexpected": True}, 3),                              # JSON без response и error
    ({"error": {"error_code": 10, "error_msg": "Internal server error"}}, 3),
    ({"error": {"error_code": 5, "error_msg": "User authorization failed"}}, 1),   # без повтора
    ({"error": {"error_code": 917, "error_msg": "You don't have access to this chat"}}, 1),
])
def test_vk_failure_keeps_booking(db_path, caplog, answer, calls):
    session = ScriptedSession(answer)
    client = make_client(db_path, session)
    with caplog.at_level(logging.ERROR, logger="app"):
        r = client.post("/api/bookings", json=booking_data())
    assert_saved_not_notified(client, r)
    assert session.calls == calls
    assert "не отправлена в ВК" in caplog.text
    assert "fake-token-for-tests" not in caplog.text          # токен не попадает в журнал


def test_vk_recovers_after_temporary_error(db_path):
    session = ScriptedSession(requests.Timeout(), {"error": {"error_code": 6, "error_msg": "Too many"}},
                              {"response": 77})
    client = make_client(db_path, session)
    r = client.post("/api/bookings", json=booking_data())
    assert r.status_code == 201 and r.get_json()["notified"] is True
    assert session.calls == 3


def test_unexpected_notifier_error(db_path, caplog):
    class Broken:
        def send_booking(self, booking):
            raise RuntimeError("сбой модуля")
    client = app_module.create_app(db_path, notifier=Broken()).test_client()
    with caplog.at_level(logging.ERROR, logger="app"):
        r = client.post("/api/bookings", json=booking_data())
    assert_saved_not_notified(client, r)
    assert "непредвиденная ошибка" in caplog.text


def test_vk_not_configured(db_path, monkeypatch):
    monkeypatch.delenv("VK_TOKEN", raising=False)
    monkeypatch.delenv("VK_PEER_ID", raising=False)
    client = app_module.create_app(db_path).test_client()
    assert_saved_not_notified(client, client.post("/api/bookings", json=booking_data()))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_real_connection_refused(db_path):
    """Настоящий сетевой запрос на закрытый порт: ВК «выключен»."""
    api = vk.VkApi("fake-token-for-tests", host=f"127.0.0.1:{free_port()}", sleep=lambda s: None,
                   timeout=2)
    client = app_module.create_app(db_path, notifier=vk.VkNotifier(api, PEER)).test_client()
    assert_saved_not_notified(client, client.post("/api/bookings", json=booking_data()))


def test_real_timeout(db_path):
    """Настоящий тайм-аут: сервер принимает соединение и молчит. Ответ гостю
    приходит не позже чем через attempts × timeout, бронь сохранена."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    conns = []
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conns.append(srv.accept()[0])
            except OSError:
                pass
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    try:
        api = vk.VkApi("fake-token-for-tests", host="127.0.0.1:%d" % srv.getsockname()[1],
                       attempts=2, sleep=lambda s: None, timeout=0.5)
        client = app_module.create_app(db_path, notifier=vk.VkNotifier(api, PEER)).test_client()
        started = time.monotonic()
        r = client.post("/api/bookings", json=booking_data())
        elapsed = time.monotonic() - started
        assert_saved_not_notified(client, r)
        assert len(conns) == 2                                # две попытки
        assert elapsed < 3
    finally:
        stop.set()
        t.join()
        for c in conns:
            c.close()
        srv.close()


def test_timeout_from_env():
    n = vk.VkNotifier.from_env({"VK_TOKEN": "x", "VK_PEER_ID": "2000000001", "VK_TIMEOUT": "4.5"})
    assert n.api.timeout == 4.5


# ---------- бот: сбои ВК и Long Poll не останавливают обработку ----------
class FlakyLongPoll:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = 0

    def get(self, url, params=None, timeout=None):
        self.requests += 1
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return FakeResponse(a)


class BotApi:
    def __init__(self, fail_refresh=False):
        self.calls = []
        self.fail_refresh = fail_refresh

    def call(self, method, **p):
        self.calls.append(method)
        if method == "groups.getLongPollServer":
            if self.fail_refresh and self.calls.count(method) > 1:
                raise vk.VkError("network", "ConnectionError")
            return {"server": "https://lp.vk.test", "key": "k", "ts": "1"}
        if method == "users.get":
            raise vk.VkError(10, "Internal server error")       # имя администратора не получено
        return 1


def booked(db_path):
    c = app_module.create_app(db_path, notifier=None).test_client()
    return c, c.post("/api/bookings", json=booking_data()).get_json()["id"]


def event(booking_id):
    return {"type": "message_event", "object": {
        "user_id": 42, "peer_id": PEER, "event_id": "e", "conversation_message_id": 1,
        "payload": {"action": "confirm", "booking_id": booking_id}}}


def test_bot_survives_network_errors(db_path, caplog):
    client, bid = booked(db_path)
    api = BotApi(fail_refresh=True)
    lp = FlakyLongPoll(requests.ConnectionError(), ValueError("не JSON"), {"failed": 2},
                       {"failed": 1, "ts": "5"}, {"ts": "6", "updates": [event(bid)]})
    bot = vk_bot.BookingBot(api, db_path, PEER)
    with caplog.at_level(logging.WARNING, logger="vk_bot"):
        bot.run(1, session=lp, stop=lambda: lp.requests >= 5, sleep=lambda s: None)
    assert client.get(f"/api/bookings/{bid}").get_json()["status"] == "confirmed"
    assert "Long Poll недоступен" in caplog.text
    assert "Не удалось обновить сервер Long Poll" in caplog.text


def test_bot_admin_name_fallback(db_path, caplog):
    client, bid = booked(db_path)
    edits = []
    api = BotApi()
    orig = api.call

    def call(method, **p):
        if method == "messages.edit":
            edits.append(p["message"])
        return orig(method, **p)
    api.call = call
    vk_bot.BookingBot(api, db_path, PEER).handle_event(event(bid)["object"])
    assert edits[0].endswith("✅ Подтверждено: id42")           # users.get недоступен


def test_bot_vk_error_on_edit_is_logged(db_path, caplog):
    client, bid = booked(db_path)

    class EditFails(BotApi):
        def call(self, method, **p):
            if method == "messages.edit":
                raise vk.VkError(10, "Internal server error")
            return super().call(method, **p)
    lp = FlakyLongPoll({"ts": "2", "updates": [event(bid)]})
    with caplog.at_level(logging.ERROR, logger="vk_bot"):
        vk_bot.BookingBot(EditFails(), db_path, PEER).run(
            1, session=lp, stop=lambda: lp.requests >= 1, sleep=lambda s: None)
    assert "Ошибка ВК при обработке кнопки" in caplog.text
    # решение администратора уже сохранено в базе
    assert client.get(f"/api/bookings/{bid}").get_json()["status"] == "confirmed"


def test_bot_start_without_rights():
    """Ключ без права «Управление сообществом»: ВК отвечает ошибкой 15, бот сообщает об этом."""
    class NoRights:
        def call(self, method, **p):
            raise vk.VkError(15, "Access denied: no access to call this method")
    with pytest.raises(vk.VkError) as e:
        vk_bot.BookingBot(NoRights(), "unused.sqlite", PEER).run(1)
    assert e.value.code == 15


# ---------- неверные данные ----------
BAD_BOOKINGS = [
    (dict(date="20.11.2026"), 400, "Дата должна быть"),
    (dict(date=PAST), 400, "прошедшую дату"),
    (dict(date=None), 400, "Дата должна быть"),
    (dict(start="25:00"), 400, "Поле start"),
    (dict(end="9 вечера"), 400, "Поле end"),
    (dict(start="21:00", end="19:00"), 400, "позже времени начала"),
    (dict(start="19:00", end="19:00"), 400, "позже времени начала"),
    (dict(guests=0), 400, "больше нуля"),
    (dict(guests=-3), 400, "больше нуля"),
    (dict(guests="четыре"), 400, "целым числом"),
    (dict(guests=2.5), 400, "целым числом"),
    (dict(guests=51), 400, "не может быть больше 50"),
    (dict(name="   "), 400, "Укажите ФИО"),
    (dict(name="А" * 101), 400, "не должно быть длиннее"),
    (dict(phone="12345"), 400, "Телефон"),
    (dict(phone="+7900123456a"), 400, "Телефон"),
    (dict(email="не-email"), 400, "Email"),
    (dict(table_id=None), 400, "Не указан столик"),
    (dict(table_id="три"), 400, "Не указан столик"),
    (dict(table_id=True), 400, "Не указан столик"),
    (dict(table_id=999), 404, "Столик не найден"),
    (dict(table_id=1, guests=3), 400, "рассчитан на 2"),
    (dict(name="'); DROP TABLE bookings; --"), 201, None),   # параметры запроса, не SQL
    (dict(name="<script>alert(1)</script>"), 201, None),     # сохраняется как текст
]


@pytest.mark.parametrize("change, code, text", BAD_BOOKINGS)
def test_bad_booking(client, vk_server, change, code, text):
    r = client.post("/api/bookings", json=booking_data(**change))
    assert r.status_code == code
    if text:
        assert text in r.get_json()["error"]
        assert vk_server.messages == []                       # в ВК ничего не уходит
    else:
        assert r.get_json()["guest"]["name"] == change["name"]
    assert len(client.get("/api/halls").get_json()) == 2      # база цела


@pytest.mark.parametrize("body, kwargs", [
    (None, dict(data="не json", content_type="application/json")),
    (None, dict(data="name=Иван", content_type="application/x-www-form-urlencoded")),
    ([1, 2, 3], {}),
    ("строка", {}),
])
def test_body_not_object(client, body, kwargs):
    r = client.post("/api/bookings", json=body, **kwargs) if body is not None \
        else client.post("/api/bookings", **kwargs)
    assert r.status_code == 400
    assert r.get_json()["error"] == "Ожидается JSON-объект"


@pytest.mark.parametrize("query, text", [
    ("start=19:00&end=21:00", "Дата должна быть"),
    (f"date={DAY}&start=19:00&end=18:00", "позже времени начала"),
    (f"date={DAY}&start=19:00&end=21:00&guests=0", "больше нуля"),
    (f"date={DAY}&start=19:00&end=21:00&hall_id=abc", "Номер зала"),
    (f"date={PAST}&start=19:00&end=21:00", "прошедшую дату"),
])
def test_bad_free_tables_query(client, query, text):
    r = client.get("/api/tables/free?" + query)
    assert r.status_code == 400 and text in r.get_json()["error"]


def test_bad_hall_in_scheme(client):
    r = client.get("/api/tables?hall_id=1 OR 1=1")
    assert r.status_code == 400 and "Номер зала" in r.get_json()["error"]
    assert client.get("/api/tables?hall_id=99").get_json() == []


def test_http_errors_are_json(client):
    for r, code in [(client.get("/api/nope"), 404), (client.get("/api/bookings/999"), 404),
                    (client.post("/api/bookings/999/cancel"), 404), (client.get("/api/bookings/abc"), 404),
                    (client.get("/api/bookings"), 405), (client.delete("/api/halls"), 405)]:
        assert r.status_code == code
        assert "error" in r.get_json()


def test_internal_error_is_json(db_path, monkeypatch):
    flask_app = app_module.create_app(db_path, notifier=None)
    flask_app.config["DB_PATH"] = "/nonexistent/dir/db.sqlite"   # база недоступна
    r = flask_app.test_client().get("/api/halls")
    assert r.status_code == 500
    assert r.get_json()["error"].startswith("Внутренняя ошибка сервера")
