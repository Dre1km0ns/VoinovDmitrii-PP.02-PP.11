"""ПП.11, этап 2. API бронирования столиков в кафе (Flask).

Эндпоинты:
  GET  /api/halls                       — залы
  GET  /api/tables/free                 — свободные столики на дату и интервал
  POST /api/bookings                    — создать бронь (с проверкой пересечений)
  GET  /api/bookings/<id>               — посмотреть бронь
  POST /api/bookings/<id>/cancel        — отменить бронь
"""
import os
import re
from datetime import datetime

from flask import Flask, g, jsonify, request

import db

ACTIVE = ("new", "confirmed")          # брони, которые занимают столик
SITE_USER_ID = 1                       # служебный пользователь «сайт»
PHONE_RE = re.compile(r"^\+7\d{10}$")


class ValidationError(Exception):
    pass


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path or os.environ.get(
        "BOOKING_DB", os.path.join(db.BASE_DIR, "booking.sqlite"))
    app.json.ensure_ascii = False
    db.init_db(app.config["DB_PATH"])

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

    # ---------- проверка входных данных ----------
    def parse_date(value):
        try:
            return datetime.strptime(value or "", "%Y-%m-%d").date().isoformat()
        except ValueError:
            raise ValidationError("Дата должна быть в формате ГГГГ-ММ-ДД")

    def parse_time(value, name):
        try:
            return datetime.strptime(value or "", "%H:%M").strftime("%H:%M")
        except ValueError:
            raise ValidationError(f"Поле {name} должно быть в формате ЧЧ:ММ")

    def parse_interval(src):
        date = parse_date(src.get("date"))
        start = parse_time(src.get("start"), "start")
        end = parse_time(src.get("end"), "end")
        if start >= end:
            raise ValidationError("Время окончания должно быть позже времени начала")
        return date, start, end

    def parse_guests(value):
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ValidationError("Количество гостей должно быть целым числом")
        if n <= 0:
            raise ValidationError("Количество гостей должно быть больше нуля")
        return n

    # ---------- проверка пересечения по времени ----------
    def has_overlap(c, table_id, date, start, end):
        """Интервалы [start, end) пересекаются, если начало одного раньше конца другого и наоборот."""
        row = c.execute(
            "SELECT 1 FROM bookings WHERE table_id = ? AND date = ? "
            "AND status IN (?, ?) AND time_start < ? AND ? < time_end LIMIT 1",
            (table_id, date, *ACTIVE, end, start)).fetchone()
        return row is not None

    def booking_json(c, booking_id):
        r = c.execute(
            "SELECT b.id, b.date, b.time_start, b.time_end, b.guests_count, b.status, b.created_at, "
            "g.full_name, g.phone, g.email, t.id AS table_id, t.number, t.capacity, h.name AS hall "
            "FROM bookings b JOIN guests g ON g.id = b.guest_id "
            "JOIN cafe_tables t ON t.id = b.table_id JOIN halls h ON h.id = t.hall_id "
            "WHERE b.id = ?", (booking_id,)).fetchone()
        if r is None:
            return None
        return {"id": r["id"], "date": r["date"], "start": r["time_start"], "end": r["time_end"],
                "guests": r["guests_count"], "status": r["status"], "created_at": r["created_at"],
                "guest": {"name": r["full_name"], "phone": r["phone"], "email": r["email"]},
                "table": {"id": r["table_id"], "number": r["number"],
                          "capacity": r["capacity"], "hall": r["hall"]}}

    # ---------- эндпоинты ----------
    @app.get("/api/halls")
    def halls():
        rows = conn().execute("SELECT id, name, description FROM halls ORDER BY id").fetchall()
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
        if request.args.get("hall_id"):
            sql += " AND h.id = ?"
            params.append(request.args.get("hall_id"))
        rows = conn().execute(sql + " ORDER BY h.id, t.number", params).fetchall()
        return jsonify([dict(r) for r in rows])

    @app.post("/api/bookings")
    def create_booking():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError("Ожидается JSON-объект")
        date, start, end = parse_interval(data)
        guests = parse_guests(data.get("guests"))
        name = (data.get("name") or "").strip()
        phone = re.sub(r"[\s()-]", "", data.get("phone") or "")
        email = (data.get("email") or "").strip() or None
        if not name:
            raise ValidationError("Укажите ФИО")
        if not PHONE_RE.match(phone):
            raise ValidationError("Телефон должен быть в формате +7XXXXXXXXXX")
        try:
            table_id = int(data.get("table_id"))
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
        return jsonify(booking_json(c, booking_id)), 201

    @app.get("/api/bookings/<int:booking_id>")
    def get_booking(booking_id):
        b = booking_json(conn(), booking_id)
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
        return jsonify(booking_json(c, booking_id))

    return app


if __name__ == "__main__":
    create_app().run(debug=False, port=int(os.environ.get("PORT", 5000)))
