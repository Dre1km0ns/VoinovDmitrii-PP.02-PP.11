"""ПП.02, этап 8. Тесты ограничений целостности (NOT NULL, CHECK, UNIQUE, FK)."""
import psycopg2
import pytest

from tests.conftest import run

E = psycopg2.errors
BOOK = ("INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, "
        "guests_count, status) VALUES ({g}, {t}, 1, current_date + 20, '{s}', '{e}', {n}, '{st}')")


def book(g=1, t=1, s="10:00", e="11:00", n=2, st="new"):
    return BOOK.format(g=g, t=t, s=s, e=e, n=n, st=st)


CASES = [
    ("гость без телефона", "INSERT INTO cafe.guests (full_name) VALUES ('Х')", E.NotNullViolation),
    ("пустое ФИО", "INSERT INTO cafe.guests (full_name, phone) VALUES ('  ', '+79990000003')", E.CheckViolation),
    ("телефон 8916…", "INSERT INTO cafe.guests (full_name, phone) VALUES ('Х', '89161234567')", E.CheckViolation),
    ("повтор телефона", "INSERT INTO cafe.guests (full_name, phone) VALUES ('Х', '+79161234501')", E.UniqueViolation),
    ("неверный email", "INSERT INTO cafe.guests (full_name, phone, email) VALUES ('Х', '+79990000004', 'a@b')", E.CheckViolation),
    ("повтор названия зала", "INSERT INTO cafe.halls (name) VALUES ('VIP')", E.UniqueViolation),
    ("повтор номера столика в зале", "INSERT INTO cafe.cafe_tables (hall_id, number, capacity) VALUES (1, 1, 2)", E.UniqueViolation),
    ("вместимость 0", "INSERT INTO cafe.cafe_tables (hall_id, number, capacity) VALUES (1, 20, 0)", E.CheckViolation),
    ("вместимость 21", "INSERT INTO cafe.cafe_tables (hall_id, number, capacity) VALUES (1, 20, 21)", E.CheckViolation),
    ("столик в несуществующем зале", "INSERT INTO cafe.cafe_tables (hall_id, number, capacity) VALUES (99, 1, 2)", E.ForeignKeyViolation),
    ("окончание раньше начала", book(s="12:00", e="11:00"), E.CheckViolation),
    ("окончание равно началу", book(s="12:00", e="12:00"), E.CheckViolation),
    ("0 гостей", book(n=0), E.CheckViolation),
    ("неизвестный статус", book(st="done"), E.CheckViolation),
    ("несуществующий гость", book(g=999), E.ForeignKeyViolation),
    ("несуществующий столик", book(t=999), E.ForeignKeyViolation),
    ("удалить зал со столиками", "DELETE FROM cafe.halls WHERE id = 1", E.ForeignKeyViolation),
    ("удалить гостя с бронями", "DELETE FROM cafe.guests WHERE id = 1", E.ForeignKeyViolation),
    ("неизвестная роль", "INSERT INTO cafe.roles (name) VALUES ('root')", E.CheckViolation),
    ("логин с пробелом", "INSERT INTO cafe.users (login, full_name, role_id) VALUES ('a b', 'Х', 2)", E.CheckViolation),
    ("повтор логина", "INSERT INTO cafe.users (login, full_name, role_id) VALUES ('site', 'Х', 2)", E.UniqueViolation),
]


@pytest.mark.parametrize("title, sql, error", CASES, ids=[c[0] for c in CASES])
def test_constraint(db, title, sql, error):
    with pytest.raises(error):
        run(db["owner"], sql)


def test_valid_rows_pass(db):
    o = db["owner"]
    gid = run(o, "INSERT INTO cafe.guests (full_name, phone, email) VALUES ('Новый', '+79990000005', 'n@example.com') RETURNING id")[0][0]
    rows = run(o, book(g=gid) + " RETURNING status, created_at IS NOT NULL")
    assert rows == [("new", True)]
    assert run(o, "INSERT INTO cafe.users (login, full_name, role_id) VALUES ('new.user', 'Х', 2) RETURNING password_hash") == [("!",)]
