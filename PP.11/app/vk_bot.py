"""ПП.11, этапы 3–4. Обработка кнопок «Подтвердить»/«Отклонить» в беседе администраторов.

Работает через Bots Long Poll API: ждёт события message_event (нажатие
callback-кнопки), меняет статус брони в базе, дописывает в сообщение, кто
принял решение, убирает кнопки и отвечает ВК всплывающим уведомлением.

Запуск (рядом с app.py, с той же базой):
    python vk_bot.py
"""
import json
import logging
import os
import sqlite3
import time

import requests

import db
import vk

log = logging.getLogger("vk_bot")

DECISIONS = {"confirm": ("confirmed", "✅ Подтверждено"),
             "reject": ("rejected", "❌ Отклонено")}


class BookingBot:
    def __init__(self, api, db_path, peer_id, prefix=""):
        self.api = api
        self.db_path = db_path
        self.peer_id = int(peer_id)
        self.prefix = prefix

    def admin_name(self, user_id):
        try:
            u = self.api.call("users.get", user_ids=user_id)[0]
            return f"{u['first_name']} {u['last_name']}"
        except (vk.VkError, IndexError, KeyError):
            return f"id{user_id}"

    def answer(self, event, text):
        """Всплывающее уведомление нажавшему (убирает индикатор загрузки на кнопке)."""
        self.api.call("messages.sendMessageEventAnswer", event_id=event["event_id"],
                      user_id=event["user_id"], peer_id=event["peer_id"],
                      event_data=json.dumps({"type": "show_snackbar", "text": text},
                                            ensure_ascii=False))

    def handle_event(self, event):
        """Обработать одно событие message_event. Возвращает итог для журнала."""
        if event.get("peer_id") != self.peer_id:
            return "чужая беседа, пропуск"
        payload = event.get("payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                payload = {}
        decision = DECISIONS.get(payload.get("action"))
        try:
            booking_id = int(payload.get("booking_id"))
        except (TypeError, ValueError):
            booking_id = None
        if decision is None or booking_id is None:
            self.answer(event, "Неизвестная кнопка")
            return "неизвестная кнопка"

        status, verdict = decision
        conn = db.connect(self.db_path)
        try:
            changed = db.decide_booking(conn, booking_id, status)
            booking = db.get_booking(conn, booking_id)
        finally:
            conn.close()
        if booking is None:
            self.answer(event, f"Бронь №{booking_id} не найдена")
            return "бронь не найдена"
        if not changed:
            current = vk.STATUS_RU.get(booking["status"], booking["status"])
            self.answer(event, f"Бронь №{booking_id} уже {current}")
            return f"бронь уже {current}"

        who = self.admin_name(event["user_id"])
        text = vk.format_booking(booking, self.prefix) + f"\n{verdict}: {who}"
        self.api.call("messages.edit", peer_id=event["peer_id"],
                      conversation_message_id=event["conversation_message_id"],
                      message=text, keyboard=vk.EMPTY_KEYBOARD)
        self.answer(event, f"Бронь №{booking_id} {vk.STATUS_RU[status]}")
        return f"бронь №{booking_id} → {status} ({who})"

    def run(self, group_id, session=None, stop=lambda: False, sleep=time.sleep):
        """Цикл Bots Long Poll. Ключ сервера, как и токен, в журнал не выводится.

        Этап 4: сбои сети и ВК не останавливают бота — он пишет предупреждение,
        делает паузу и продолжает. Ошибка при первом получении сервера (например,
        15 «нет доступа» у ключа без права «Управление сообществом») выбрасывается
        сразу, потому что без неё бот работать не может."""
        session = session or requests.Session()
        server = self.api.call("groups.getLongPollServer", group_id=group_id)
        log.info("Бот запущен, ожидаю нажатия кнопок")
        while not stop():
            try:
                r = session.get(server["server"], params={
                    "act": "a_check", "key": server["key"], "ts": server["ts"], "wait": 25},
                    timeout=35).json()
            except (requests.RequestException, ValueError) as e:
                log.warning("Long Poll недоступен: %s, повтор через 3 с", type(e).__name__)
                sleep(3)
                continue
            if "failed" in r:
                if r["failed"] == 1:
                    server["ts"] = r["ts"]
                else:                          # ключ устарел — получить новый
                    try:
                        server = self.api.call("groups.getLongPollServer", group_id=group_id)
                    except vk.VkError as e:
                        log.warning("Не удалось обновить сервер Long Poll: %s, повтор через 3 с", e)
                        sleep(3)
                continue
            server["ts"] = r.get("ts", server["ts"])
            for upd in r.get("updates", []):
                if upd.get("type") != "message_event":
                    continue
                try:
                    log.info("Кнопка: %s", self.handle_event(upd["object"]))
                except vk.VkError as e:
                    log.error("Ошибка ВК при обработке кнопки: %s", e)
                except sqlite3.Error as e:
                    log.error("Ошибка базы данных при обработке кнопки: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    api = vk.VkApi(os.environ["VK_TOKEN"], host=os.environ.get("VK_API_HOST", vk.DEFAULT_HOST))
    db_path = os.environ.get("BOOKING_DB", os.path.join(db.BASE_DIR, "booking.sqlite"))
    bot = BookingBot(api, db_path, os.environ["VK_PEER_ID"], os.environ.get("VK_MESSAGE_PREFIX", ""))
    bot.run(os.environ["VK_GROUP_ID"])
