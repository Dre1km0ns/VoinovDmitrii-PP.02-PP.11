-- ПП.02, этап 8 (неделя 4). Логика базы данных: триггеры и представления.
--   триггеры: запрет двойной брони столика на пересекающееся время,
--             проверка вместимости столика;
--   представления: брони с расшифровкой, загрузка залов по датам.
-- Выполняется суперпользователем после скриптов недель 2 и 3:
--   psql -d cafe_booking -v ON_ERROR_STOP=1 -f 04_logic.sql

\set ON_ERROR_STOP on
SET client_min_messages = warning;
SET search_path = cafe;

-- ======================= Триггеры =======================
-- Активными считаются брони в статусах new и confirmed: только они занимают столик.

-- 1. Проверка вместимости: гостей не больше, чем мест за столиком
CREATE FUNCTION check_booking_capacity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_capacity smallint;
    v_number smallint;
BEGIN
    IF NEW.status NOT IN ('new', 'confirmed') THEN
        RETURN NEW;                                   -- отменённая/отклонённая бронь места не занимает
    END IF;
    SELECT capacity, number INTO v_capacity, v_number FROM cafe.cafe_tables WHERE id = NEW.table_id;
    IF FOUND AND NEW.guests_count > v_capacity THEN
        RAISE EXCEPTION 'Столик №% рассчитан на % гостей, в брони указано %',
                        v_number, v_capacity, NEW.guests_count
            USING ERRCODE = 'check_violation', HINT = 'Выберите столик большей вместимости';
    END IF;
    RETURN NEW;
END $$;

-- 2. Запрет двойной брони: у активных броней одного столика в одну дату интервалы
--    [начало; окончание) не пересекаются. Строка столика блокируется (FOR NO KEY UPDATE),
--    поэтому две одновременные транзакции не смогут занять столик на одно время.
CREATE FUNCTION check_booking_overlap() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_other record;
BEGIN
    IF NEW.status NOT IN ('new', 'confirmed') THEN
        RETURN NEW;
    END IF;
    PERFORM 1 FROM cafe.cafe_tables WHERE id = NEW.table_id FOR NO KEY UPDATE;
    SELECT b.id, b.time_start, b.time_end INTO v_other
    FROM cafe.bookings b
    WHERE b.table_id = NEW.table_id AND b.booking_date = NEW.booking_date
      AND b.status IN ('new', 'confirmed') AND b.id <> NEW.id
      AND b.time_start < NEW.time_end AND NEW.time_start < b.time_end
    LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Столик уже забронирован на это время: бронь №% (% – %)',
                        v_other.id, to_char(v_other.time_start, 'HH24:MI'), to_char(v_other.time_end, 'HH24:MI')
            USING ERRCODE = 'exclusion_violation';
    END IF;
    RETURN NEW;
END $$;

-- Триггеры одного события срабатывают по алфавиту: сначала вместимость, затем пересечение
CREATE TRIGGER trg_bookings_1_capacity
    BEFORE INSERT OR UPDATE OF table_id, guests_count, status ON bookings
    FOR EACH ROW EXECUTE FUNCTION check_booking_capacity();
CREATE TRIGGER trg_bookings_2_no_overlap
    BEFORE INSERT OR UPDATE OF table_id, booking_date, time_start, time_end, status ON bookings
    FOR EACH ROW EXECUTE FUNCTION check_booking_overlap();

-- 3. Вместимость столика нельзя уменьшить, если на него есть предстоящие активные брони на большее число гостей
CREATE FUNCTION check_table_capacity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_id bigint;
    v_guests smallint;
BEGIN
    SELECT id, guests_count INTO v_id, v_guests FROM cafe.bookings
    WHERE table_id = NEW.id AND status IN ('new', 'confirmed') AND booking_date >= current_date
      AND guests_count > NEW.capacity
    ORDER BY guests_count DESC LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Нельзя уменьшить вместимость до %: в брони №% указано % гостей',
                        NEW.capacity, v_id, v_guests USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_cafe_tables_capacity
    BEFORE UPDATE OF capacity ON cafe_tables
    FOR EACH ROW WHEN (NEW.capacity < OLD.capacity) EXECUTE FUNCTION check_table_capacity();

REVOKE EXECUTE ON FUNCTION check_booking_capacity(), check_booking_overlap(), check_table_capacity() FROM PUBLIC;

-- ======================= Представления =======================
-- security_invoker = true: права проверяются у того, кто читает представление,
-- поэтому через представление нельзя увидеть больше, чем разрешено роли.

-- Брони с расшифровкой: гость, зал, столик, кто оформил, статус по-русски
CREATE VIEW v_bookings WITH (security_invoker = true) AS
SELECT b.id,
       b.booking_date,
       b.time_start,
       b.time_end,
       h.name        AS hall,
       t.number      AS table_number,
       t.capacity,
       b.guests_count,
       g.full_name   AS guest,
       g.phone,
       CASE b.status WHEN 'new' THEN 'новая' WHEN 'confirmed' THEN 'подтверждена'
                     WHEN 'rejected' THEN 'отклонена' WHEN 'cancelled' THEN 'отменена' END AS status,
       u.login       AS created_by,
       b.created_at
FROM bookings b
JOIN guests g      ON g.id = b.guest_id
JOIN cafe_tables t ON t.id = b.table_id
JOIN halls h       ON h.id = t.hall_id
JOIN users u       ON u.id = b.user_id;
COMMENT ON VIEW v_bookings IS 'Брони с данными гостя, зала, столика и оформившего';

-- Загрузка залов по датам: активные брони, гости, занятые столики, места зала
CREATE VIEW v_hall_load WITH (security_invoker = true) AS
SELECT b.booking_date,
       h.name                                   AS hall,
       count(*)                                 AS active_bookings,
       sum(b.guests_count)                      AS guests,
       count(DISTINCT b.table_id)               AS tables_booked,
       (SELECT count(*) FROM cafe_tables t2 WHERE t2.hall_id = h.id)          AS tables_total,
       (SELECT sum(t2.capacity) FROM cafe_tables t2 WHERE t2.hall_id = h.id) AS seats_total
FROM bookings b
JOIN cafe_tables t ON t.id = b.table_id
JOIN halls h       ON h.id = t.hall_id
WHERE b.status IN ('new', 'confirmed')
GROUP BY b.booking_date, h.id, h.name;
COMMENT ON VIEW v_hall_load IS 'Загрузка залов по датам (только активные брони)';

GRANT SELECT ON v_bookings, v_hall_load TO cafe_admin, cafe_manager;
