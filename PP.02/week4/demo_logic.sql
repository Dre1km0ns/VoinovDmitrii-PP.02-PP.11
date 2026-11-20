-- ПП.02, этап 8. Демонстрация триггеров и представлений (ошибки в разделах 1–3 ожидаемы).
-- psql -d cafe_booking -f demo_logic.sql
\pset footer off
\set ON_ERROR_STOP off
\set ON_ERROR_ROLLBACK on
SET search_path = cafe;
BEGIN;
\echo '=== 1. Двойная бронь: столик 3 завтра занят бронью №1 (19:00–21:00) ==='
\echo '-- 1.1 то же время'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (2, 3, 1, current_date + 1, '19:00', '21:00', 2);
\echo '-- 1.2 частичное пересечение 20:00–22:00'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (2, 3, 1, current_date + 1, '20:00', '22:00', 2);
\echo '-- 1.3 через функцию сайта create_booking'
SELECT create_booking('Гость', '+79990005555', NULL, 3, current_date + 1, '18:30', '19:30', 2);
\echo '-- 1.4 впритык до брони №1 (17:00–19:00) — разрешено'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (2, 3, 1, current_date + 1, '17:00', '19:00', 2) RETURNING id;
\echo '-- 1.5 вернуть отклонённую бронь №6 (19:30–20:30) в статус new'
UPDATE bookings SET status = 'new' WHERE id = 6;
\echo '=== 2. Вместимость ==='
\echo '-- 2.1 5 гостей за столик на 4 места'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (2, 2, 1, current_date + 5, '12:00', '13:00', 5);
\echo '-- 2.2 увеличить число гостей в брони №1 до 6'
UPDATE bookings SET guests_count = 6 WHERE id = 1;
\echo '-- 2.3 уменьшить вместимость столика 4 до 4 (бронь №3 на 5 гостей)'
UPDATE cafe_tables SET capacity = 4 WHERE id = 4;
\echo '=== 3. Представление v_bookings (брони на завтра) ==='
SELECT id, hall, table_number AS "стол", time_start, time_end, guests_count AS "гостей", guest, status, created_by
FROM v_bookings WHERE booking_date = current_date + 1 ORDER BY hall, table_number, time_start;
\echo '=== 4. Представление v_hall_load (загрузка залов) ==='
SELECT booking_date, hall, active_bookings AS "броней", guests AS "гостей",
       tables_booked || ' из ' || tables_total AS "столиков", seats_total AS "мест"
FROM v_hall_load ORDER BY booking_date, hall;
ROLLBACK;
