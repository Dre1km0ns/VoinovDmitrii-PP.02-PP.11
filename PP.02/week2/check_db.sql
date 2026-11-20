-- ПП.02, этап 6. Проверка созданной базы: структура, данные, ограничения.
-- Запуск: psql -d cafe_booking -f check_db.sql   (ошибки в разделе 5 ожидаемы)
\pset footer off
SET search_path = cafe;
\echo '=== 1. Таблицы схемы cafe ==='
\dt cafe.*
\echo '=== 2. Структура таблицы bookings ==='
\d cafe.bookings
\echo '=== 3. Ограничения (PK, FK, UNIQUE, CHECK) ==='
SELECT conrelid::regclass AS "таблица", conname AS "ограничение",
       CASE contype WHEN 'p' THEN 'PK' WHEN 'f' THEN 'FK' WHEN 'u' THEN 'UNIQUE' WHEN 'c' THEN 'CHECK' END AS "тип"
FROM pg_constraint WHERE connamespace = 'cafe'::regnamespace
ORDER BY conrelid::regclass::text, contype, conname;
\echo '=== 4. Индексы ==='
SELECT tablename AS "таблица", indexname AS "индекс" FROM pg_indexes WHERE schemaname = 'cafe' ORDER BY 1, 2;
\echo '=== 5. Количество строк ==='
SELECT 'roles' AS "таблица", count(*) AS "строк" FROM roles UNION ALL
SELECT 'users', count(*) FROM users UNION ALL SELECT 'guests', count(*) FROM guests UNION ALL
SELECT 'halls', count(*) FROM halls UNION ALL SELECT 'cafe_tables', count(*) FROM cafe_tables UNION ALL
SELECT 'bookings', count(*) FROM bookings;
\echo '=== 6. Брони на завтра (соединение 4 таблиц) ==='
SELECT b.id, h.name AS hall, t.number AS "table", b.time_start, b.time_end, b.guests_count AS guests,
       g.full_name AS guest, b.status
FROM bookings b JOIN guests g ON g.id = b.guest_id
JOIN cafe_tables t ON t.id = b.table_id JOIN halls h ON h.id = t.hall_id
WHERE b.booking_date = current_date + 1 ORDER BY h.id, t.number, b.time_start;
\echo '=== 7. Частичный индекс используется при поиске занятых столиков ==='
SET enable_seqscan = off;
EXPLAIN (COSTS OFF) SELECT table_id FROM bookings
WHERE table_id = 3 AND booking_date = current_date + 1 AND status IN ('new', 'confirmed')
  AND time_start < '21:00' AND '19:00' < time_end;
RESET enable_seqscan;
\echo '=== 8. Проверка ограничений: каждая команда должна завершиться ошибкой ==='
\set ON_ERROR_STOP off
\echo '-- 8.1 NOT NULL: гость без телефона'
INSERT INTO guests (full_name) VALUES ('Без телефона');
\echo '-- 8.2 CHECK: телефон не в формате +7XXXXXXXXXX'
INSERT INTO guests (full_name, phone) VALUES ('Гость', '89161234567');
\echo '-- 8.3 UNIQUE: повтор телефона'
INSERT INTO guests (full_name, phone) VALUES ('Двойник', '+79161234501');
\echo '-- 8.4 CHECK: неверный email'
INSERT INTO guests (full_name, phone, email) VALUES ('Гость', '+79160000000', 'не-email');
\echo '-- 8.5 UNIQUE: второй столик №1 в основном зале'
INSERT INTO cafe_tables (hall_id, number, capacity) VALUES (1, 1, 4);
\echo '-- 8.6 CHECK: вместимость 0'
INSERT INTO cafe_tables (hall_id, number, capacity) VALUES (1, 8, 0);
\echo '-- 8.7 FK: столик в несуществующем зале'
INSERT INTO cafe_tables (hall_id, number, capacity) VALUES (99, 1, 4);
\echo '-- 8.8 CHECK: окончание брони раньше начала'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (1, 1, 1, current_date + 5, '20:00', '19:00', 2);
\echo '-- 8.9 CHECK: неизвестный статус'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count, status)
VALUES (1, 1, 1, current_date + 5, '19:00', '20:00', 2, 'done');
\echo '-- 8.10 CHECK: 0 гостей'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (1, 1, 1, current_date + 5, '19:00', '20:00', 0);
\echo '-- 8.11 FK: бронь несуществующего гостя'
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (999, 1, 1, current_date + 5, '19:00', '20:00', 2);
\echo '-- 8.12 FK (ON DELETE RESTRICT): удаление зала со столиками'
DELETE FROM halls WHERE id = 1;
\echo '-- 8.13 CHECK: неизвестная роль'
INSERT INTO roles (name) VALUES ('суперпользователь');
\echo '-- 8.14 CHECK: логин с пробелом'
INSERT INTO users (login, password_hash, full_name, role_id) VALUES ('bad login', '!', 'Тест', 2);
\echo '=== 9. Корректная вставка проходит ==='
BEGIN;
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
VALUES (1, 1, 1, current_date + 5, '19:00', '20:00', 2) RETURNING id, status, created_at IS NOT NULL AS has_created_at;
ROLLBACK;
