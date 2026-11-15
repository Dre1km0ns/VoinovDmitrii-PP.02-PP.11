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
