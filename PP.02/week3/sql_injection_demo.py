"""ПП.02, этап 7. SQL-инъекция: склейка строки против параметризованного запроса.

Подключение под ролью менеджера. Функция find_guest_UNSAFE — антипример, такой код
в проекте не используется; в модуле ПП.11 и в функциях базы все запросы параметризованные.
"""
import os

import psycopg2

conn = psycopg2.connect(host=os.environ.get("PGHOST", "127.0.0.1"), port=os.environ.get("PGPORT", "5432"),
                        dbname=os.environ.get("CAFE_DB", "cafe_booking"), user="cafe_manager_petrov",
                        password=os.environ["CAFE_MANAGER_DB_PASSWORD"])
conn.autocommit = True


def find_guest_UNSAFE(phone):
    """ОПАСНО: значение вставляется прямо в текст SQL."""
    sql = "SELECT id, full_name, phone FROM cafe.guests WHERE phone = '" + phone + "'"
    cur = conn.cursor()
    cur.execute(sql)
    return sql, cur.fetchall() if cur.description else []


def find_guest_safe(phone):
    """Безопасно: значение передаётся отдельно от текста запроса (параметр %s)."""
    sql = "SELECT id, full_name, phone FROM cafe.guests WHERE phone = %s"
    cur = conn.cursor()
    cur.execute(sql, (phone,))
    return sql, cur.fetchall()


for title, value in [("обычный ввод", "+79161234501"),
                     ("инъекция: выдать всех гостей", "' OR '1'='1"),
                     ("инъекция: удалить брони", "'; DELETE FROM cafe.bookings; --")]:
    print(f"\n=== {title}: {value!r} ===")
    for fn in (find_guest_UNSAFE, find_guest_safe):
        try:
            sql, rows = fn(value)
            print(f"  {fn.__name__:18} найдено строк: {len(rows)}")
            if fn is find_guest_UNSAFE:
                print(f"  {'':18} выполнен SQL: {sql}")
        except psycopg2.Error as e:
            print(f"  {fn.__name__:18} ОШИБКА СУБД: {e.pgerror.splitlines()[0]}")
cur = conn.cursor()
cur.execute("SELECT count(*) FROM cafe.bookings")
print(f"\nБроней в базе после попыток: {cur.fetchone()[0]} — удаление не прошло "
      "(у менеджера нет права DELETE, а параметризованный запрос не выполняет внедрённый SQL)")
