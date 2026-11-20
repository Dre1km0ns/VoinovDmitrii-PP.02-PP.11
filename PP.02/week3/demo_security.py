"""ПП.02, этап 7. Демонстрация механизмов защиты базы cafe_booking.

Подключается под ролями администратора, менеджера и сайта (гостя) и проверяет,
что разрешённые действия выполняются, а запрещённые отклоняются СУБД.
Пароли ролей берутся из тех же переменных окружения, что и в 03_security.sql;
пароли пользователей приложения генерируются при запуске и никуда не сохраняются.
    python demo_security.py > demo_output.txt
"""
import os
import secrets
import subprocess
from datetime import date, timedelta

import psycopg2

HOST = dict(host=os.environ.get("PGHOST", "127.0.0.1"), port=os.environ.get("PGPORT", "5432"),
            dbname=os.environ.get("CAFE_DB", "cafe_booking"))
ROLES = {"admin": ("cafe_admin_ivanova", "CAFE_ADMIN_DB_PASSWORD"),
         "manager": ("cafe_manager_petrov", "CAFE_MANAGER_DB_PASSWORD"),
         "web": ("cafe_web", "CAFE_WEB_DB_PASSWORD")}
DAY = date.today() + timedelta(days=10)


def connect(who):
    if who == "owner":
        c = psycopg2.connect(user=os.environ.get("PGUSER", "postgres"),
                             password=os.environ.get("PGPASSWORD"), **HOST)
    else:
        user, env = ROLES[who]
        c = psycopg2.connect(user=user, password=os.environ[env], **HOST)
    c.autocommit = True
    return c


def attempt(conn, title, sql, params=None, show=True):
    """Выполнить запрос и напечатать РАЗРЕШЕНО (с результатом) или ЗАПРЕЩЕНО (с ошибкой СУБД)."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
        res = f"{len(rows)} строк" if rows is not None else f"изменено строк: {cur.rowcount}"
        print(f"  РАЗРЕШЕНО  {title}: {res}")
        if show and rows:
            for r in rows[:3]:
                print("             ", r)
        return rows
    except psycopg2.Error as e:
        print(f"  ЗАПРЕЩЕНО  {title}: {e.pgerror.splitlines()[0] if e.pgerror else e}")
        return None


def section(t):
    print(f"\n=== {t} ===")


owner, admin, manager, web = connect("owner"), connect("admin"), connect("manager"), connect("web")

section("1. Роли и их членство")
cur = owner.cursor()
cur.execute("""SELECT r.rolname, CASE WHEN r.rolcanlogin THEN 'вход' ELSE 'группа' END,
                      coalesce(string_agg(g.rolname, ', '), '—')
               FROM pg_roles r LEFT JOIN pg_auth_members m ON m.member = r.oid
               LEFT JOIN pg_roles g ON g.oid = m.roleid
               WHERE r.rolname LIKE 'cafe%' GROUP BY 1, 2 ORDER BY 2 DESC, 1""")
for row in cur.fetchall():
    print("  %-22s %-7s член: %s" % row)

section("2. Матрица прав на таблицы (has_any_column_privilege, has_table_privilege)")
cur.execute("""SELECT g.r, t.t,
       concat_ws(' ', CASE WHEN has_any_column_privilege(g.r, 'cafe.'||t.t, 'SELECT') THEN 'S' END,
                      CASE WHEN has_any_column_privilege(g.r, 'cafe.'||t.t, 'INSERT') THEN 'I' END,
                      CASE WHEN has_any_column_privilege(g.r, 'cafe.'||t.t, 'UPDATE') THEN 'U' END,
                      CASE WHEN has_table_privilege(g.r, 'cafe.'||t.t, 'DELETE') THEN 'D' END)
    FROM unnest(ARRAY['cafe_admin','cafe_manager','cafe_guest']) g(r),
         unnest(ARRAY['roles','users','guests','halls','cafe_tables','bookings','audit_log']) t(t)""")
m = {}
for r, t, p in cur.fetchall():
    m.setdefault(t, {})[r] = p or "—"
print("  %-12s %-14s %-14s %-14s" % ("таблица", "cafe_admin", "cafe_manager", "cafe_guest"))
for t, d in m.items():
    print("  %-12s %-14s %-14s %-14s" % (t, d["cafe_admin"], d["cafe_manager"], d["cafe_guest"]))
print("  (S, I, U — SELECT, INSERT, UPDATE хотя бы одного столбца; D — DELETE)")

section("3. Администратор (cafe_admin_ivanova)")
attempt(admin, "добавить зал", "INSERT INTO cafe.halls (name, description) VALUES ('Терраса', 'тест') RETURNING id")
attempt(admin, "переименовать зал", "UPDATE cafe.halls SET description = 'Летняя терраса' WHERE name = 'Терраса'")
attempt(admin, "удалить зал", "DELETE FROM cafe.halls WHERE name = 'Терраса'")
attempt(admin, "список пользователей без хешей", "SELECT id, login, role_id FROM cafe.users ORDER BY id")
attempt(admin, "прочитать хеши паролей", "SELECT login, password_hash FROM cafe.users")
attempt(admin, "прочитать журнал аудита", "SELECT count(*) FROM cafe.audit_log")
attempt(admin, "исправить запись журнала", "UPDATE cafe.audit_log SET db_user = 'кто-то'")
attempt(admin, "удалить журнал", "DELETE FROM cafe.audit_log")

section("4. Менеджер (cafe_manager_petrov)")
attempt(manager, "брони на завтра", "SELECT id, table_id, status FROM cafe.bookings WHERE booking_date = current_date + 1 ORDER BY id")
attempt(manager, "подтвердить бронь №1", "UPDATE cafe.bookings SET status = 'confirmed' WHERE id = 1")
attempt(manager, "перенести бронь на другой столик", "UPDATE cafe.bookings SET table_id = 2 WHERE id = 1")
attempt(manager, "удалить бронь", "DELETE FROM cafe.bookings WHERE id = 1")
attempt(manager, "добавить гостя", "INSERT INTO cafe.guests (full_name, phone) VALUES ('Новый Гость', '+79990000001') RETURNING id")
attempt(manager, "прочитать хеши паролей", "SELECT password_hash FROM cafe.users")
attempt(manager, "добавить столик", "INSERT INTO cafe.cafe_tables (hall_id, number, capacity) VALUES (1, 9, 4)")
attempt(manager, "прочитать журнал аудита", "SELECT * FROM cafe.audit_log")
attempt(manager, "задать пароль пользователю", "SELECT cafe.set_password('manager.petrov', 'Qwerty12345')")

section("5. Гость — сайт (cafe_web)")
attempt(web, "залы и столики", "SELECT h.name, count(*) FROM cafe.halls h JOIN cafe.cafe_tables t ON t.hall_id = h.id GROUP BY 1")
attempt(web, "свободные столики через функцию", "SELECT * FROM cafe.free_tables(%s, '19:00', '21:00', 4)", (DAY,))
attempt(web, "забронировать через функцию",
        "SELECT cafe.create_booking(%s, %s, %s, %s, %s, %s, %s, %s)",
        ("Гость Сайта", "+79990000002", "", 3, DAY, "19:00", "21:00", 4))
attempt(web, "прочитать гостей (персональные данные)", "SELECT full_name, phone FROM cafe.guests")
attempt(web, "прочитать брони", "SELECT * FROM cafe.bookings")
attempt(web, "вставить бронь напрямую", "INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count) VALUES (1, 1, 1, %s, '10:00', '11:00', 2)", (DAY,))
attempt(web, "прочитать пользователей", "SELECT login FROM cafe.users")

section("6. Хеширование паролей")
pw = {"admin.ivanova": secrets.token_urlsafe(9) + "7a", "manager.petrov": secrets.token_urlsafe(9) + "5b"}
for login, p in pw.items():
    attempt(admin, f"set_password('{login}', <случайный пароль>)", "SELECT cafe.set_password(%s, %s)", (login, p), show=False)
attempt(admin, "слабый пароль 'qwerty'", "SELECT cafe.set_password('manager.sidorova', 'qwerty')")
cur.execute("SELECT login, left(password_hash, 29) || '…', length(password_hash) FROM cafe.users ORDER BY id")
print("  Хранится (выведено владельцем базы):")
for row in cur.fetchall():
    print("    %-17s %-31s длина %s" % row)
cur.execute("SELECT password_hash FROM cafe.users WHERE login = 'admin.ivanova'")
print("  Открытого пароля в хеше нет:", pw["admin.ivanova"] not in cur.fetchone()[0])
attempt(web, "вход manager.petrov с верным паролем", "SELECT * FROM cafe.check_password(%s, %s)", ("manager.petrov", pw["manager.petrov"]))
attempt(web, "вход с неверным паролем (пустой ответ = отказ)", "SELECT * FROM cafe.check_password(%s, %s)", ("manager.petrov", "WrongPass1"))
attempt(web, "вход записи site без пароля (пустой ответ = отказ)", "SELECT * FROM cafe.check_password('site', '!')")
attempt(owner, "записать пароль открытым текстом", "UPDATE cafe.users SET password_hash = '12345678' WHERE login = 'manager.sidorova'")

section("7. Журнал аудита (последние записи)")
cur.execute("""SELECT id, to_char(changed_at, 'HH24:MI:SS'), db_user, operation, table_name, row_id,
                      old_data, new_data FROM cafe.audit_log ORDER BY id""")
for i, t, user, op, table, row_id, old, new in cur.fetchall():
    if op == "UPDATE":                     # для изменения — только изменившиеся поля
        data = ", ".join(f"{k}: {old.get(k)} → {new[k]}" for k in new if old.get(k) != new[k])
    else:
        data = ", ".join(f"{k}: {v}" for k, v in (new or old).items() if k != "created_at")
    data = data if len(data) < 80 else data[:77] + "…"
    print("  №%-3s %s %-20s %-6s %-11s id=%-3s %s" % (i, t, user, op, table, row_id, data))
attempt(owner, "владелец базы удаляет записи журнала", "DELETE FROM cafe.audit_log WHERE id = 1")
attempt(owner, "владелец базы очищает журнал", "TRUNCATE cafe.audit_log")
