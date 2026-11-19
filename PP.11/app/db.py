"""Подключение к рабочему черновику БД (SQLite) и начальное заполнение.

Таблицы повторяют модель этапа 5 (PP.02/week1). Официальный скрипт БД
и механизмы защиты делаются на этапах 6–8 (ПП.02).
"""
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(BASE_DIR, "schema_draft.sql")


def connect(path):
    conn = sqlite3.connect(path, isolation_level=None)  # транзакции управляем явно
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path):
    """Создать таблицы и минимальный справочник (залы, столики, роли), если база пустая."""
    conn = connect(path)
    with open(SCHEMA, encoding="utf-8") as f:
        conn.executescript(f.read())
    if conn.execute("SELECT COUNT(*) FROM halls").fetchone()[0] == 0:
        conn.execute("BEGIN")
        conn.executemany("INSERT INTO roles(id, name) VALUES (?, ?)",
                         [(1, "администратор"), (2, "менеджер"), (3, "гость")])
        # Служебная учётная запись «сайт»: от её имени оформляются брони из веб-формы.
        # Вход под ней невозможен ('!' не является хешем); хеширование паролей — этап 7.
        conn.execute("INSERT INTO users(id, login, password_hash, full_name, role_id) "
                     "VALUES (1, 'site', '!', 'Онлайн-бронирование', 3)")
        conn.executemany("INSERT INTO halls(id, name, description) VALUES (?, ?, ?)",
                         [(1, "Основной", "Основной зал"), (2, "Веранда", "Летняя веранда")])
        conn.executemany("INSERT INTO cafe_tables(hall_id, number, capacity) VALUES (?, ?, ?)",
                         [(1, 1, 2), (1, 2, 4), (1, 3, 4), (1, 4, 6),
                          (1, 5, 2), (1, 6, 4), (1, 7, 2), (2, 1, 4), (2, 2, 8)])
        conn.execute("COMMIT")
    conn.close()


def get_booking(conn, booking_id):
    """Бронь с данными гостя, столика и зала (словарь) или None."""
    r = conn.execute(
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


def decide_booking(conn, booking_id, status):
    """Решение администратора: перевести «новую» бронь в confirmed или rejected.

    Возвращает True, если статус изменён; False, если бронь уже не «новая»
    (например, её успел обработать другой администратор или гость отменил)."""
    if status not in ("confirmed", "rejected"):
        raise ValueError(status)
    cur = conn.execute("UPDATE bookings SET status = ? WHERE id = ? AND status = 'new'",
                       (status, booking_id))
    return cur.rowcount == 1
