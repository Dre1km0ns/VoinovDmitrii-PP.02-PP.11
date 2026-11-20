"""ПП.02, этап 8. Тесты прав доступа ролей администратора, менеджера и гостя (сайта)."""
import psycopg2
import pytest

from tests.conftest import run

D = "current_date + 20"
CASES = [
    # (роль, описание, SQL, разрешено)
    ("admin", "добавить зал", "INSERT INTO cafe.halls (name) VALUES ('Тест')", True),
    ("admin", "изменить вместимость столика", "UPDATE cafe.cafe_tables SET capacity = 5 WHERE id = 2", True),
    ("admin", "удалить отменённую бронь", "DELETE FROM cafe.bookings WHERE status = 'cancelled'", True),
    ("admin", "список пользователей", "SELECT id, login, full_name, role_id FROM cafe.users", True),
    ("admin", "хеши паролей", "SELECT password_hash FROM cafe.users", False),
    ("admin", "записать хеш напрямую", "UPDATE cafe.users SET password_hash = '!' WHERE id = 2", False),
    ("admin", "читать журнал аудита", "SELECT * FROM cafe.audit_log", True),
    ("admin", "изменить журнал аудита", "UPDATE cafe.audit_log SET db_user = 'x'", False),
    ("admin", "удалить журнал аудита", "DELETE FROM cafe.audit_log", False),
    ("admin", "представление v_bookings", "SELECT * FROM cafe.v_bookings", True),
    ("manager", "читать брони", "SELECT * FROM cafe.bookings", True),
    ("manager", "сменить статус брони", "UPDATE cafe.bookings SET status = 'confirmed' WHERE id = 1", True),
    ("manager", "перенести бронь на другой столик", "UPDATE cafe.bookings SET table_id = 2 WHERE id = 1", False),
    ("manager", "удалить бронь", "DELETE FROM cafe.bookings WHERE id = 1", False),
    ("manager", "добавить гостя", "INSERT INTO cafe.guests (full_name, phone) VALUES ('Тест', '+79990001111')", True),
    ("manager", "изменить телефон гостя", "UPDATE cafe.guests SET phone = '+79990001112' WHERE id = 1", False),
    ("manager", "удалить гостя", "DELETE FROM cafe.guests WHERE id = 10", False),
    ("manager", "добавить зал", "INSERT INTO cafe.halls (name) VALUES ('Тест')", False),
    ("manager", "изменить столик", "UPDATE cafe.cafe_tables SET capacity = 10 WHERE id = 1", False),
    ("manager", "хеши паролей", "SELECT password_hash FROM cafe.users", False),
    ("manager", "логины пользователей", "SELECT login FROM cafe.users", True),
    ("manager", "журнал аудита", "SELECT * FROM cafe.audit_log", False),
    ("manager", "задать пароль", "SELECT cafe.set_password('site', 'Password123')", False),
    ("manager", "представления", "SELECT * FROM cafe.v_bookings, cafe.v_hall_load LIMIT 1", True),
    ("web", "залы и столики", "SELECT * FROM cafe.halls, cafe.cafe_tables", True),
    ("web", "гости", "SELECT * FROM cafe.guests", False),
    ("web", "брони", "SELECT * FROM cafe.bookings", False),
    ("web", "пользователи", "SELECT login FROM cafe.users", False),
    ("web", "вставить бронь напрямую",
     f"INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count) "
     f"VALUES (1, 1, 1, {D}, '10:00', '11:00', 2)", False),
    ("web", "изменить зал", "UPDATE cafe.halls SET name = 'Х' WHERE id = 1", False),
    ("web", "представление v_bookings (персональные данные)", "SELECT * FROM cafe.v_bookings", False),
    ("web", "представление v_hall_load", "SELECT * FROM cafe.v_hall_load", False),
    ("web", "свободные столики (функция)", f"SELECT * FROM cafe.free_tables({D}, '19:00', '21:00', 2)", True),
    ("web", "забронировать (функция)",
     f"SELECT cafe.create_booking('Тест Сайт', '+79990002222', NULL, 1, {D}, '10:00', '11:00', 2)", True),
    ("web", "задать пароль", "SELECT cafe.set_password('site', 'Password123')", False),
    ("web", "создать таблицу в схеме cafe", "CREATE TABLE cafe.hack (id int)", False),
    ("web", "создать таблицу в схеме public", "CREATE TABLE public.hack (id int)", False),
]


@pytest.mark.parametrize("who, title, sql, allowed", CASES, ids=[f"{c[0]}: {c[1]}" for c in CASES])
def test_privilege(db, who, title, sql, allowed):
    if allowed:
        run(db[who], sql)
    else:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            run(db[who], sql)


def test_backup_role_reads_only(connect):
    c = connect("backup")
    cur = c.cursor()
    cur.execute("SELECT count(*) FROM cafe.bookings")
    assert cur.fetchone()[0] > 0
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        cur.execute("DELETE FROM cafe.bookings")
    c.rollback()


def test_public_has_no_rights(db):
    rows = run(db["owner"], """SELECT count(*) FROM information_schema.role_table_grants
                               WHERE table_schema = 'cafe' AND grantee = 'PUBLIC'""")
    assert rows[0][0] == 0


def test_password_hashing(db):
    admin, web, owner = db["admin"], db["web"], db["owner"]
    run(admin, "SELECT cafe.set_password('manager.petrov', 'Secret12345')")
    admin.commit()                                   # остальные подключения видят новый хеш
    h = run(owner, "SELECT password_hash FROM cafe.users WHERE login = 'manager.petrov'")[0][0]
    assert h.startswith("$2a$10$") and len(h) == 60 and "Secret12345" not in h
    assert run(web, "SELECT role_name FROM cafe.check_password('manager.petrov', 'Secret12345')") == [("менеджер",)]
    assert run(web, "SELECT * FROM cafe.check_password('manager.petrov', 'secret12345')") == []
    assert run(web, "SELECT * FROM cafe.check_password('manager.petrov'' --', 'x')") == []
    with pytest.raises(psycopg2.errors.CheckViolation):
        run(admin, "SELECT cafe.set_password('manager.petrov', 'short1')")
    with pytest.raises(psycopg2.errors.CheckViolation):
        run(owner, "UPDATE cafe.users SET password_hash = 'Secret12345' WHERE login = 'manager.petrov'")


def test_audit_log_records_changes(db):
    manager, admin = db["manager"], db["admin"]
    run(manager, "UPDATE cafe.bookings SET status = 'confirmed' WHERE id = 11")
    manager.commit()
    row = run(admin, """SELECT db_user, operation, old_data->>'status', new_data->>'status'
                        FROM cafe.audit_log WHERE table_name = 'bookings' AND row_id = 11
                        ORDER BY id DESC LIMIT 1""")
    assert row == [("cafe_manager_petrov", "UPDATE", "new", "confirmed")]
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        run(db["owner"], "DELETE FROM cafe.audit_log")
