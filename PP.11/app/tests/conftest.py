"""Общие фикстуры pytest (ПП.11, этап 4)."""
import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module   # noqa: E402
import vk                  # noqa: E402

DAY = (date.today() + timedelta(days=7)).isoformat()      # всегда будущая дата
PEER = 2000000001


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class FakeVkSession:
    """Заглушка сервера VK API: messages.send сохраняет сообщение (как беседа),
    остальные методы отвечают успехом. Настоящий ВКонтакте в тестах не вызывается."""

    def __init__(self):
        self.calls = []
        self.messages = []          # «беседа администраторов»

    def post(self, url, data=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, dict(data)))
        if method == "messages.send":
            self.messages.append({"id": len(self.messages) + 1, "peer_id": int(data["peer_id"]),
                                  "conversation_message_id": len(self.messages) + 1,
                                  "text": data["message"], "keyboard": json.loads(data["keyboard"])})
            return FakeResponse({"response": len(self.messages)})
        if method == "users.get":
            return FakeResponse({"response": [{"first_name": "Пётр", "last_name": "Петров"}]})
        if method == "groups.getLongPollServer":
            return FakeResponse({"response": {"server": "https://lp.vk.test", "key": "k", "ts": "1"}})
        return FakeResponse({"response": 1})

    def methods(self):
        return [m for m, _ in self.calls]


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.sqlite")


@pytest.fixture
def vk_server():
    return FakeVkSession()


@pytest.fixture
def vk_api(vk_server):
    return vk.VkApi("fake-token-for-tests", session=vk_server, sleep=lambda s: None)


@pytest.fixture
def client(db_path, vk_api):
    notifier = vk.VkNotifier(vk_api, PEER)
    return app_module.create_app(db_path, notifier=notifier).test_client()


def booking_data(**kw):
    data = dict(name="Иванов Иван", phone="+7 900 123-45-67", email="ivan@example.com",
                table_id=3, date=DAY, start="19:00", end="21:00", guests=4)
    data.update(kw)
    return data
