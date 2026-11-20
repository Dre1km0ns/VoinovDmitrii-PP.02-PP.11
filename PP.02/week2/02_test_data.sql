-- ПП.02, этап 6 (неделя 2). Тестовые данные.
-- Даты броней считаются от текущей даты, поэтому данные не устаревают.
\set ON_ERROR_STOP on
SET search_path = cafe;

BEGIN;

INSERT INTO roles (id, name) VALUES
    (1, 'администратор'), (2, 'менеджер'), (3, 'гость');

-- Пароли задаются на этапе 7 (хеширование); до этого «!» — вход запрещён.
INSERT INTO users (id, login, password_hash, full_name, role_id) VALUES
    (1, 'site',          '!', 'Онлайн-бронирование (сайт)', 3),
    (2, 'admin.ivanova', '!', 'Иванова Анна Сергеевна',     1),
    (3, 'manager.petrov','!', 'Петров Олег Викторович',     2),
    (4, 'manager.sidorova','!','Сидорова Мария Игоревна',   2);

INSERT INTO halls (id, name, description) VALUES
    (1, 'Основной', 'Основной зал на 1 этаже'),
    (2, 'Веранда',  'Летняя веранда'),
    (3, 'VIP',      'Отдельный зал для банкетов');

INSERT INTO cafe_tables (id, hall_id, number, capacity) VALUES
    (1, 1, 1, 2), (2, 1, 2, 4), (3, 1, 3, 4), (4, 1, 4, 6), (5, 1, 5, 2), (6, 1, 6, 4), (7, 1, 7, 2),
    (8, 2, 1, 4), (9, 2, 2, 8), (10, 2, 3, 4),
    (11, 3, 1, 10), (12, 3, 2, 12);

INSERT INTO guests (id, full_name, phone, email) VALUES
    (1,  'Смирнов Алексей',      '+79161234501', 'smirnov@example.com'),
    (2,  'Кузнецова Ольга',      '+79161234502', NULL),
    (3,  'Попов Дмитрий',        '+79161234503', 'popov@example.com'),
    (4,  'Васильева Екатерина',  '+79161234504', NULL),
    (5,  'Новиков Игорь',        '+79161234505', 'novikov@example.com'),
    (6,  'Морозова Анастасия',   '+79161234506', NULL),
    (7,  'Волков Сергей',        '+79161234507', 'volkov@example.com'),
    (8,  'Соколова Дарья',       '+79161234508', NULL),
    (9,  'Лебедев Павел',        '+79161234509', 'lebedev@example.com'),
    (10, 'Козлова Виктория',     '+79161234510', NULL);

-- Активные брони (new, confirmed) одного столика по времени не пересекаются.
INSERT INTO bookings (guest_id, table_id, user_id, booking_date, time_start, time_end,
                      guests_count, status, created_at) VALUES
    (1, 3, 1, current_date + 1, '19:00', '21:00', 4, 'new',       now() - interval '2 hours'),
    (2, 1, 1, current_date + 1, '12:00', '13:30', 2, 'confirmed', now() - interval '1 day'),
    (3, 4, 3, current_date + 1, '18:00', '20:00', 5, 'confirmed', now() - interval '1 day'),
    (4, 9, 1, current_date + 1, '17:00', '19:00', 8, 'new',       now() - interval '3 hours'),
    (5, 3, 1, current_date + 1, '21:00', '23:00', 3, 'new',       now() - interval '1 hour'),
    (6, 3, 1, current_date + 1, '19:30', '20:30', 2, 'rejected',  now() - interval '5 hours'),
    (7, 11, 2, current_date + 2, '18:00', '23:00', 10, 'confirmed', now() - interval '2 days'),
    (8, 2, 1, current_date + 2, '13:00', '14:00', 2, 'cancelled', now() - interval '1 day'),
    (8, 2, 1, current_date + 2, '14:00', '15:30', 3, 'new',       now() - interval '20 hours'),
    (9, 8, 4, current_date + 2, '20:00', '22:00', 4, 'confirmed', now() - interval '1 day'),
    (10, 6, 1, current_date + 3, '19:00', '21:00', 4, 'new',      now() - interval '30 minutes'),
    (1, 12, 3, current_date + 7, '16:00', '22:00', 12, 'confirmed', now() - interval '3 days'),
    (2, 5, 1, current_date - 1, '19:00', '20:00', 2, 'confirmed', now() - interval '4 days'),
    (3, 7, 1, current_date - 1, '13:00', '14:00', 1, 'cancelled', now() - interval '4 days'),
    (4, 10, 4, current_date + 3, '12:00', '14:00', 4, 'new',      now() - interval '10 minutes');

-- Счётчики автонумерации после вставки с явными id
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['roles', 'users', 'halls', 'cafe_tables', 'guests'] LOOP
        EXECUTE format('SELECT setval(pg_get_serial_sequence(%L, ''id''), (SELECT max(id) FROM cafe.%I))',
                       'cafe.' || t, t);
    END LOOP;
END $$;

COMMIT;
