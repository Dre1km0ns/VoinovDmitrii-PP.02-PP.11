"""ПП.11, этап 4. Сквозной тест всего сценария бронирования.

Гость → веб-форма и API → бронь в базе → сообщение в беседу администраторов ВК →
нажатие «Подтвердить»/«Отклонить» → статус брони → отмена гостем.
ВКонтакте заменён заглушкой (FakeVkSession). Нажатие callback-кнопки имитируется
событием message_event в формате Bots Long Poll: у текущего ключа сообщества нет
права «Управление сообществом», поэтому настоящие нажатия до бота не доходят.
"""
import json

import vk_bot
from tests.conftest import DAY, PEER, FakeResponse, booking_data


class LongPoll:
    """Заглушка сервера Long Poll: отдаёт заданные события один раз."""

    def __init__(self, events):
        self.batches = [{"ts": "2", "updates": events}]
        self.requests = []

    def get(self, url, params=None, timeout=None):
        self.requests.append(dict(params))
        return FakeResponse(self.batches.pop(0) if self.batches else {"ts": "3", "updates": []})


def press(message, label, user_id=42):
    """Событие message_event: администратор нажал кнопку с подписью label в сообщении."""
    button = next(b for row in message["keyboard"]["buttons"] for b in row
                  if b["action"]["label"] == label)
    return {"type": "message_event", "object": {
        "user_id": user_id, "peer_id": message["peer_id"], "event_id": "ev-" + label,
        "conversation_message_id": message["conversation_message_id"],
        "payload": json.loads(button["action"]["payload"])}}


def run_bot(vk_api, db_path, *events):
    bot = vk_bot.BookingBot(vk_api, db_path, PEER)
    lp = LongPoll(list(events))
    bot.run(230000000, session=lp, stop=lambda: len(lp.requests) >= 1, sleep=lambda s: None)
    return lp


def test_full_scenario_confirm(client, vk_server, vk_api, db_path):
    # 1. Гость открывает форму и выбирает зал, дату и время
    assert client.get("/").status_code == 200
    halls = client.get("/api/halls").get_json()
    assert [h["name"] for h in halls] == ["Основной", "Веранда"]
    scheme = client.get("/api/tables?hall_id=1").get_json()
    q = f"date={DAY}&start=19:00&end=21:00&guests=4&hall_id=1"
    free = client.get("/api/tables/free?" + q).get_json()
    assert len(scheme) == 7
    assert {t["number"] for t in free} == {2, 3, 4, 6}        # столики на 4 места и больше

    # 2. Гость выбирает столик №3 и отправляет контакты
    r = client.post("/api/bookings", json=booking_data())
    assert r.status_code == 201
    b = r.get_json()
    assert b["status"] == "new" and b["notified"] is True
    assert b["guest"]["phone"] == "+79001234567"

    # 3. В беседу администраторов пришло сообщение с данными и кнопками
    assert len(vk_server.messages) == 1
    msg = vk_server.messages[0]
    assert msg["peer_id"] == PEER
    assert f"Новая бронь №{b['id']}" in msg["text"] and "Иванов Иван" in msg["text"]
    labels = [btn["action"]["label"] for row in msg["keyboard"]["buttons"] for btn in row]
    assert labels == ["Подтвердить", "Отклонить"]

    # 4. Столик пропал из свободных, повторная бронь на пересекающееся время — 409
    free = client.get("/api/tables/free?" + q).get_json()
    assert 3 not in {t["id"] for t in free}
    r2 = client.post("/api/bookings", json=booking_data(start="20:00", end="22:00",
                                                        phone="+79005556677"))
    assert r2.status_code == 409
    assert len(vk_server.messages) == 1                         # отказ в ВК не отправляется
    # соседний интервал (21:00–23:00) не пересекается — бронь проходит
    assert client.post("/api/bookings", json=booking_data(start="21:00", end="23:00")).status_code == 201

    # 5. Администратор нажимает «Подтвердить» (имитация события Long Poll)
    run_bot(vk_api, db_path, press(msg, "Подтвердить"))
    assert client.get(f"/api/bookings/{b['id']}").get_json()["status"] == "confirmed"
    edit = [p for m, p in vk_server.calls if m == "messages.edit"][-1]
    assert "✅ Подтверждено: Пётр Петров" in edit["message"]
    assert json.loads(edit["keyboard"])["buttons"] == []        # кнопки убраны

    # 6. Второй администратор нажимает «Отклонить» — статус не меняется
    run_bot(vk_api, db_path, press(msg, "Отклонить", user_id=43))
    assert client.get(f"/api/bookings/{b['id']}").get_json()["status"] == "confirmed"
    answer = [p for m, p in vk_server.calls if m == "messages.sendMessageEventAnswer"][-1]
    assert "уже подтверждена" in answer["event_data"]

    # 7. Гость отменяет бронь — столик снова свободен; повторная отмена — 409
    assert client.post(f"/api/bookings/{b['id']}/cancel").get_json()["status"] == "cancelled"
    assert client.post(f"/api/bookings/{b['id']}/cancel").status_code == 409
    free = client.get("/api/tables/free?" + q).get_json()
    assert 3 in {t["id"] for t in free}


def test_full_scenario_reject(client, vk_server, vk_api, db_path):
    b = client.post("/api/bookings", json=booking_data(table_id=9, guests=8, start="12:00",
                                                       end="14:00")).get_json()
    assert b["table"]["hall"] == "Веранда"
    run_bot(vk_api, db_path, press(vk_server.messages[0], "Отклонить"))
    assert client.get(f"/api/bookings/{b['id']}").get_json()["status"] == "rejected"
    edit = [p for m, p in vk_server.calls if m == "messages.edit"][-1]
    assert "❌ Отклонено: Пётр Петров" in edit["message"]
    # отклонённая бронь освобождает столик, её нельзя отменить
    free = client.get(f"/api/tables/free?date={DAY}&start=12:00&end=14:00&guests=8").get_json()
    assert [t["id"] for t in free] == [9]
    assert client.post(f"/api/bookings/{b['id']}/cancel").status_code == 409


def test_guest_reuses_record_by_phone(client):
    client.post("/api/bookings", json=booking_data())
    r = client.post("/api/bookings", json=booking_data(name="Иванов Иван Иванович", table_id=1,
                                                       guests=2, email=""))
    b = r.get_json()
    assert r.status_code == 201
    assert b["guest"]["name"] == "Иванов Иван Иванович"
    assert b["guest"]["email"] == "ivan@example.com"            # пустой email не стирает старый


def test_form_page_and_static(client):
    page = client.get("/")
    assert "Бронирование столиков" in page.get_data(as_text=True)
    page.close()
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "Сервер недоступен" in js.get_data(as_text=True)
    js.close()
