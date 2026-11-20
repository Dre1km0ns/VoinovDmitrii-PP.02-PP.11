"""ПП.11, этапы 2–4. API бронирования столиков в кафе (Flask) и веб-форма.

Эндпоинты:
  GET  /                                — веб-форма брони со схемой зала (этап 3)
  GET  /api/halls                       — залы
  GET  /api/tables?hall_id=             — все столики зала для схемы (этап 3)
  GET  /api/tables/free                 — свободные столики на дату и интервал
  POST /api/bookings                    — создать бронь (с проверкой пересечений)
  GET  /api/bookings/<id>               — посмотреть бронь
  POST /api/bookings/<id>/cancel        — отменить бронь

После создания брони данные отправляются в беседу администраторов ВКонтакте
(модуль vk.py), кнопки «Подтвердить»/«Отклонить» обрабатывает vk_bot.py.
"""
import logging
import os
import re
from datetime import date as date_cls, datetime

from flask import Flask, g, jsonify, request

import db
import vk

log = logging.getLogger("app")

ACTIVE = ("new", "confirmed")          # брони, которые занимают столик
SITE_USER_ID = 1                       # служебный пользователь «сайт»
PHONE_RE = re.compile(r"^\+7\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_MAX = 100                         # длина ФИО
EMAIL_MAX = 100
GUESTS_MAX = 50                        # больше гостей — заведомо ошибка ввода


class ValidationError(Exception):
    pass


def create_app(db_path=None, notifier=None):
    """notifier — объект с методом send_booking(booking); по умолчанию берётся
    из переменных окружения (VK_TOKEN, VK_PEER_ID), без них отправка отключена."""
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["DB_PATH"] = db_path or os.environ.get(
        "BOOKING_DB", os.path.join(db.BASE_DIR, "booking.sqlite"))
    app.json.ensure_ascii = False
    db.init_db(app.config["DB_PATH"])
    if notifier is None:
        notifier = vk.VkNotifier.from_env()
        if notifier is None:
            log.warning("ВКонтакте не настроен (нет VK_TOKEN или VK_PEER_ID): брони не пересылаются")

    def notify_admins(booking):
        """Переслать бронь в беседу администраторов. Возвращает True, если сообщение
        отправлено. Любая ошибка ВК (недоступен, тайм-аут, неверный токен, ответ не JSON
        и т. п.) не отменяет бронь: она уже сохранена со статусом «новая», ошибка
        пишется в журнал, а гость получает обычный ответ 201."""
        if notifier is None:
            return False
        try:
            message_id = notifier.send_booking(booking)
        except vk.VkError as e:
            log.error("Бронь №%s не отправлена в ВК: %s", booking["id"], e)
            return False
        except Exception:                              # непредвиденная ошибка модуля ВК
            log.exception("Бронь №%s не отправлена в ВК: непредвиденная ошибка", booking["id"])
            return False
        log.info("Бронь №%s отправлена в беседу администраторов, сообщение ВК %s",
                 booking["id"], message_id)
        return True

    def conn():
        if "conn" not in g:
            g.conn = db.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.errorhandler(ValidationError)
    def bad_request(e):
        return jsonify(error=str(e)), 400

    # Ошибки HTTP и непредвиденные ошибки сервера отдаются в JSON, а не HTML-страницей,
    # чтобы веб-форма могла показать понятный текст.
    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="Не найдено"), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return jsonify(error="Метод не поддерживается"), 405

    @app.errorhandler(500)
    def server_error(_e):
        log.exception("Внутренняя ошибка сервера")
        return jsonify(error="Внутренняя ошибка сервера, попробуйте позже"), 500

    # ---------- проверка входных данных ----------
    def parse_date(value):
        try:
            d = datetime.strptime(str(value or ""), "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError("Дата должна быть в формате ГГГГ-ММ-ДД")
        if d < date_cls.today():
            raise ValidationError("Нельзя забронировать столик на прошедшую дату")
        return d.isoformat()

    def parse_time(value, name):
        try:
            return datetime.strptime(str(value or ""), "%H:%M").strftime("%H:%M")
        except ValueError:
            raise ValidationError(f"Поле {name} должно быть в формате ЧЧ:ММ")

    def parse_interval(src):
        date = parse_date(src.get("date"))
        start = parse_time(src.get("start"), "start")
        end = parse_time(src.get("end"), "end")
        if start >= end:
            raise ValidationError("Время окончания должно быть позже времени начала")
        return date, start, end

    def parse_int(value):
        """Целое число из запроса; дробные, логические и строки с буквами не принимаются."""
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError(value)
        return int(value)

    def parse_guests(value):
        try:
            n = parse_int(value)
        except (TypeError, ValueError):
            raise ValidationError("Количество гостей должно быть целым числом")
        if n <= 0:
            raise ValidationError("Количество гостей должно быть больше нуля")
        if n > GUESTS_MAX:
            raise ValidationError(f"Количество гостей не может быть больше {GUESTS_MAX}")
        return n

    def parse_hall(args):
        if not args.get("hall_id"):
            return None
        try:
            return parse_int(args.get("hall_id"))
        except ValueError:
            raise ValidationError("Номер зала должен быть целым числом")

    # ---------- проверка пересечения по времени ----------
    def has_overlap(c, table_id, date, start, end):
        """Интервалы [start, end) пересекаются, если начало одного раньше конца другого и наоборот."""
        row = c.execute(
            "SELECT 1 FROM bookings WHERE table_id = ? AND date = ? "
            "AND status IN (?, ?) AND time_start < ? AND ? < time_end LIMIT 1",
            (table_id, date, *ACTIVE, end, start)).fetchone()
        return row is not None

    # ---------- эндпоинты ----------
    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/halls")
    def halls():
        rows = conn().execute("SELECT id, name, description FROM halls ORDER BY id").fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/tables")
    def all_tables():
        """Все столики (для схемы зала); hall_id необязателен."""
        sql = ("SELECT t.id, t.number, t.capacity, h.id AS hall_id, h.name AS hall "
               "FROM cafe_tables t JOIN halls h ON h.id = t.hall_id")
        params = []
        hall_id = parse_hall(request.args)
        if hall_id is not None:
            sql += " WHERE h.id = ?"
            params.append(hall_id)
        rows = conn().execute(sql + " ORDER BY h.id, t.number", params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.get("/api/tables/free")
    def free_tables():
        date, start, end = parse_interval(request.args)
        guests = parse_guests(request.args.get("guests", 1))
        sql = ("SELECT t.id, t.number, t.capacity, h.id AS hall_id, h.name AS hall "
               "FROM cafe_tables t JOIN halls h ON h.id = t.hall_id "
               "WHERE t.capacity >= ? AND NOT EXISTS ("
               "  SELECT 1 FROM bookings b WHERE b.table_id = t.id AND b.date = ? "
               "  AND b.status IN (?, ?) AND b.time_start < ? AND ? < b.time_end)")
        params = [guests, date, *ACTIVE, end, start]
        hall_id = parse_hall(request.args)
        if hall_id is not None:
            sql += " AND h.id = ?"
            params.append(hall_id)
        rows = conn().execute(sql + " ORDER BY h.id, t.number", params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/bookings")
    def create_booking():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("Ожидается JSON-объект")
        date, start, end = parse_interval(data)
        guests = parse_guests(data.get("guests"))
        name = str(data.get("name") or "").strip()
        phone = re.sub(r"[\s()-]", "", str(data.get("phone") or ""))
        email = str(data.get("email") or "").strip() or None
        if not name:
            raise ValidationError("Укажите ФИО")
        if len(name) > NAME_MAX:
            raise ValidationError(f"ФИО не должно быть длиннее {NAME_MAX} символов")
        if not PHONE_RE.match(phone):
            raise ValidationError("Телефон должен быть в формате +7XXXXXXXXXX")
        if email is not None and (len(email) > EMAIL_MAX or not EMAIL_RE.match(email)):
            raise ValidationError("Email указан неверно")
        try:
            table_id = parse_int(data.get("table_id"))
        except (TypeError, ValueError):
            raise ValidationError("Не указан столик")

        c = conn()
        c.execute("BEGIN IMMEDIATE")   # блокировка записи: две брони не проскочат одновременно
        try:
            table = c.execute("SELECT id, capacity FROM cafe_tables WHERE id = ?",
                              (table_id,)).fetchone()
            if table is None:
                c.execute("ROLLBACK")
                return jsonify(error="Столик не найден"), 404
            if guests > table["capacity"]:
                c.execute("ROLLBACK")
                return jsonify(error=f"Столик рассчитан на {table['capacity']} гостей"), 400
            if has_overlap(c, table_id, date, start, end):
                c.execute("ROLLBACK")
                return jsonify(error="Столик уже забронирован на это время"), 409
            guest = c.execute("SELECT id FROM guests WHERE phone = ?", (phone,)).fetchone()
            if guest:
                guest_id = guest["id"]
                c.execute("UPDATE guests SET full_name = ?, email = COALESCE(?, email) WHERE id = ?",
                          (name, email, guest_id))
            else:
                guest_id = c.execute("INSERT INTO guests(full_name, phone, email) VALUES (?, ?, ?)",
                                     (name, phone, email)).lastrowid
            booking_id = c.execute(
                "INSERT INTO bookings(guest_id, table_id, user_id, date, time_start, time_end, "
                "guests_count, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'new', ?)",
                (guest_id, table_id, SITE_USER_ID, date, start, end, guests,
                 datetime.now().isoformat(timespec="seconds"))).lastrowid
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        booking = db.get_booking(c, booking_id)
        booking["notified"] = notify_admins(booking)   # дошло ли сообщение до беседы ВК
        return jsonify(booking), 201

    @app.get("/api/bookings/<int:booking_id>")
    def get_booking(booking_id):
        b = db.get_booking(conn(), booking_id)
        if b is None:
            return jsonify(error="Бронь не найдена"), 404
        return jsonify(b)

    @app.post("/api/bookings/<int:booking_id>/cancel")
    def cancel_booking(booking_id):
        c = conn()
        row = c.execute("SELECT status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if row is None:
            return jsonify(error="Бронь не найдена"), 404
        if row["status"] not in ACTIVE:
            return jsonify(error=f"Бронь в статусе {row['status']} нельзя отменить"), 409
        c.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ? AND status IN (?, ?)",
                  (booking_id, *ACTIVE))
        return jsonify(db.get_booking(c, booking_id))

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    create_app().run(debug=False, port=int(os.environ.get("PORT", 5000)))
