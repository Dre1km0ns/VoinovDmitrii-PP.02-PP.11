"""ПП.11, этапы 3–4. Пересылка данных о брони в беседу администраторов ВКонтакте.

Токен сообщества берётся только из переменной окружения VK_TOKEN и никуда
не записывается: ни в код, ни в журнал, ни в ответы API.
Запросы к VK API отправляются методом POST, поэтому токен не попадает в URL.
"""
import json
import logging
import os
import random
import time

import requests

log = logging.getLogger("vk")

API_VERSION = "5.199"
DEFAULT_HOST = "api.vk.ru"
RETRY_CODES = {6, 9, 10}      # слишком много запросов, flood control, внутренняя ошибка ВК
STATUS_RU = {"new": "новая", "confirmed": "подтверждена",
             "rejected": "отклонена", "cancelled": "отменена"}


class VkError(Exception):
    """Ошибка VK API (код и текст из ответа) или сети."""

    def __init__(self, code, message):
        super().__init__(f"VK API {code}: {message}")
        self.code = code
        self.message = message


class VkApi:
    """Минимальный клиент VK API для токена сообщества."""

    def __init__(self, token, host=DEFAULT_HOST, session=None, attempts=3, sleep=time.sleep,
                 timeout=10):
        if not token:
            raise ValueError("Не задан токен сообщества (VK_TOKEN)")
        self._token = token
        self.base = f"https://{host}/method/"
        self.session = session or requests.Session()
        self.attempts = attempts
        self.sleep = sleep
        self.timeout = timeout                # секунд на один запрос (этап 4)

    def __repr__(self):                       # токен не выводится даже при отладке
        return f"VkApi(base={self.base!r}, token=***)"

    def call(self, method, **params):
        """Вызов метода. Временные ошибки (6, 9, 10, сбой сети, тайм-аут, ответ не JSON)
        повторяются с паузой; после последней попытки выбрасывается VkError."""
        data = {k: v for k, v in params.items() if v is not None}
        data.update(access_token=self._token, v=API_VERSION)
        for attempt in range(1, self.attempts + 1):
            try:
                resp = self.session.post(self.base + method, data=data, timeout=self.timeout)
                body = resp.json()
            except (requests.RequestException, ValueError) as e:
                err = VkError("network", type(e).__name__)
            else:
                if not isinstance(body, dict) or ("response" not in body and "error" not in body):
                    err = VkError("network", "неожиданный ответ сервера")
                elif "error" not in body:
                    return body["response"]
                else:
                    err = VkError(body["error"].get("error_code"), body["error"].get("error_msg", ""))
                    if err.code not in RETRY_CODES:
                        raise err
            if attempt == self.attempts:
                raise err
            log.warning("%s: %s, повтор %d из %d", method, err, attempt, self.attempts - 1)
            self.sleep(attempt)               # пауза 1 с, 2 с, ...


# ---------- текст сообщения и кнопки ----------
def format_date(iso):
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def seats(n):
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} место"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} места"
    return f"{n} мест"


def format_booking(b, prefix=""):
    """Текст сообщения о брони (b — словарь из db.get_booking)."""
    lines = [f"{prefix}🆕 Новая бронь №{b['id']}",
             f"Гость: {b['guest']['name']}, {b['guest']['phone']}"]
    if b["guest"].get("email"):
        lines.append(f"Email: {b['guest']['email']}")
    lines += [f"Дата: {format_date(b['date'])}, {b['start']}–{b['end']}",
              f"Зал: {b['table']['hall']}, столик №{b['table']['number']} "
              f"({seats(b['table']['capacity'])})",
              f"Гостей: {b['guests']}",
              f"Статус: {STATUS_RU.get(b['status'], b['status'])}"]
    return "\n".join(lines)


def booking_keyboard(booking_id):
    """Инлайн-клавиатура с callback-кнопками «Подтвердить» и «Отклонить»."""
    def button(label, action, color):
        return {"action": {"type": "callback", "label": label,
                           "payload": json.dumps({"action": action, "booking_id": booking_id})},
                "color": color}
    return json.dumps({"inline": True, "buttons": [[
        button("Подтвердить", "confirm", "positive"),
        button("Отклонить", "reject", "negative")]]}, ensure_ascii=False)


EMPTY_KEYBOARD = json.dumps({"inline": True, "buttons": []})


class VkNotifier:
    """Отправка сообщений о бронях в беседу администраторов."""

    def __init__(self, api, peer_id, prefix=""):
        self.api = api
        self.peer_id = int(peer_id)
        self.prefix = prefix

    @classmethod
    def from_env(cls, env=os.environ):
        """Создать по переменным окружения; None, если ВК не настроен."""
        if not env.get("VK_TOKEN") or not env.get("VK_PEER_ID"):
            return None
        api = VkApi(env["VK_TOKEN"], host=env.get("VK_API_HOST", DEFAULT_HOST),
                    timeout=float(env.get("VK_TIMEOUT", 10)))
        return cls(api, env["VK_PEER_ID"], env.get("VK_MESSAGE_PREFIX", ""))

    def send_booking(self, booking):
        """Отправить сообщение о новой брони. Возвращает id сообщения ВК.

        random_id выбирается один раз и не меняется при повторах,
        поэтому повторная отправка не создаст дубликат в беседе."""
        return self.api.call("messages.send", peer_id=self.peer_id,
                             random_id=random.randint(1, 2**31 - 1),
                             message=format_booking(booking, self.prefix),
                             keyboard=booking_keyboard(booking["id"]))
