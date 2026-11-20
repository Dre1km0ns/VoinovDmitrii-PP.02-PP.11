"""ПП.02, этап 8. Тесты триггеров (двойная бронь, вместимость) и представлений."""
import threading

import psycopg2
import pytest

from tests.conftest import run

E = psycopg2.errors
D = "current_date + 15"


def book(conn, table=2, start="19:00", end="21:00", guests=2, status="new", day=D, guest=1):
    return run(conn, f"""INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start,
                         time_end, guests_count, status) VALUES ({guest}, {table}, 1, {day}, '{start}', '{end}',
                         {guests}, '{status}') RETURNING id""")[0][0]


# ---------- запрет двойной брони ----------
@pytest.mark.parametrize("start, end", [("19:00", "21:00"), ("18:00", "19:30"), ("20:30", "22:00"),
                                        ("19:30", "20:30"), ("18:00", "22:00")],
                         ids=["то же время", "пересекает начало", "пересекает конец", "внутри", "охватывает"])
def test_overlap_rejected(db, start, end):
    o = db["owner"]
    first = book(o)
    with pytest.raises(E.ExclusionViolation, match=f"бронь №{first}"):
        book(o, start=start, end=end)


@pytest.mark.parametrize("kw", [dict(start="21:00", end="22:00"), dict(start="17:00", end="19:00"),
                                dict(table=3), dict(day="current_date + 16")],
                         ids=["сразу после", "сразу до", "другой столик", "другая дата"])
def test_no_overlap_allowed(db, kw):
    o = db["owner"]
    book(o)
    book(o, **kw)


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_inactive_booking_does_not_block(db, status):
    o = db["owner"]
    book(o, status=status)
    book(o)                                          # то же время — столик свободен


def test_reactivation_checked(db):
    o = db["owner"]
    old = book(o, status="rejected")
    book(o)
    with pytest.raises(E.ExclusionViolation):
        run(o, f"UPDATE cafe.bookings SET status = 'new' WHERE id = {old}")


def test_move_to_busy_time_or_table(db):
    o = db["owner"]
    book(o)
    other = book(o, start="21:00", end="23:00")
    with pytest.raises(E.ExclusionViolation):
        run(o, f"UPDATE cafe.bookings SET time_start = '20:00' WHERE id = {other}")
    third = book(o, table=3)
    with pytest.raises(E.ExclusionViolation):
        run(o, f"UPDATE cafe.bookings SET table_id = 2 WHERE id = {third}")


def test_overlap_in_test_data_and_via_site(db):
    web = db["web"]
    # бронь №1 тестовых данных: столик 3, завтра 19:00–21:00
    with pytest.raises(E.ExclusionViolation):
        run(web, "SELECT cafe.create_booking('Гость', '+79990003333', NULL, 3, current_date + 1, '20:00', '22:00', 2)")


def test_concurrent_double_booking(connect):
    """Две транзакции одновременно бронируют один столик на одно время: проходит только одна."""
    barrier = threading.Barrier(2)
    results = []

    def worker(phone):
        c = connect("owner")
        cur = c.cursor()
        try:
            barrier.wait()
            cur.execute("""INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start,
                           time_end, guests_count) VALUES (2, 7, 1, current_date + 40, '12:00', '14:00', 2)""")
            c.commit()
            results.append("ok")
        except E.ExclusionViolation:
            c.rollback()
            results.append("отказ")
    threads = [threading.Thread(target=worker, args=(p,)) for p in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "отказ"]


# ---------- проверка вместимости ----------
def test_capacity_exceeded(db):
    with pytest.raises(E.CheckViolation, match="рассчитан на 4 гостей, в брони указано 5"):
        book(db["owner"], guests=5)


def test_capacity_exact_allowed(db):
    book(db["owner"], guests=4)


def test_capacity_on_update(db):
    o = db["owner"]
    bid = book(o, guests=2)
    with pytest.raises(E.CheckViolation):
        run(o, f"UPDATE cafe.bookings SET guests_count = 6 WHERE id = {bid}")
    with pytest.raises(E.CheckViolation):                  # перенос на столик на 2 места
        run(o, f"UPDATE cafe.bookings SET guests_count = 3, table_id = 1 WHERE id = {bid}")


def test_capacity_via_site(db):
    with pytest.raises(E.CheckViolation):
        run(db["web"], "SELECT cafe.create_booking('Гость', '+79990004444', NULL, 1, current_date + 15, '10:00', '11:00', 3)")


def test_reduce_table_capacity(db):
    o = db["owner"]
    book(o, table=4, guests=6)
    with pytest.raises(E.CheckViolation, match="Нельзя уменьшить вместимость"):
        run(o, "UPDATE cafe.cafe_tables SET capacity = 4 WHERE id = 4")
    run(o, "UPDATE cafe.cafe_tables SET capacity = 8 WHERE id = 4")   # увеличить можно


def test_cancelled_booking_ignores_capacity(db):
    book(db["owner"], guests=5, status="cancelled")


# ---------- представления ----------
def test_v_bookings(db):
    rows = run(db["manager"], """SELECT hall, table_number, guest, status, created_by FROM cafe.v_bookings
                                 WHERE id = 1""")
    assert rows == [("Основной", 3, "Смирнов Алексей", "новая", "site")]


def test_v_hall_load(db):
    rows = run(db["manager"], """SELECT hall, active_bookings, guests, tables_booked, tables_total, seats_total
                                 FROM cafe.v_hall_load WHERE booking_date = current_date + 1 ORDER BY hall""")
    # завтра: основной зал — брони 1, 2, 3, 5 (6 отклонена), веранда — бронь 4
    assert rows == [("Веранда", 1, 8, 1, 3, 16), ("Основной", 4, 14, 3, 7, 24)]


def test_views_respect_invoker_rights(db):
    with pytest.raises(E.InsufficientPrivilege):
        run(db["web"], "SELECT * FROM cafe.v_bookings")


def test_trigger_changes_are_audited(db):
    o = db["owner"]
    bid = book(o)
    rows = run(o, f"SELECT operation FROM cafe.audit_log WHERE table_name = 'bookings' AND row_id = {bid}")
    assert rows == [("INSERT",)]
