-- ПП.02, этап 7 (неделя 3). Защита базы данных cafe_booking.
--   1) роли и права доступа: администратор, менеджер, гость (сайт);
--   2) хеширование паролей пользователей (bcrypt, расширение pgcrypto);
--   3) функции со статическим SQL и параметрами (защита от SQL-инъекций);
--   4) журнал аудита изменений;
--   резервное копирование — backup.sh и restore_check.sh.
-- Выполняется суперпользователем после скриптов недели 2. Пароли ролей входа
-- берутся из переменных окружения и в репозиторий не попадают:
--   CAFE_ADMIN_DB_PASSWORD, CAFE_MANAGER_DB_PASSWORD, CAFE_WEB_DB_PASSWORD, CAFE_BACKUP_DB_PASSWORD
--   psql -d cafe_booking -v ON_ERROR_STOP=1 -f 03_security.sql

\set ON_ERROR_STOP on
SET client_min_messages = warning;
\getenv admin_pw CAFE_ADMIN_DB_PASSWORD
\getenv manager_pw CAFE_MANAGER_DB_PASSWORD
\getenv web_pw CAFE_WEB_DB_PASSWORD
\getenv backup_pw CAFE_BACKUP_DB_PASSWORD
\if :{?admin_pw}
\else
  \warn 'Не заданы пароли ролей (CAFE_*_DB_PASSWORD) — скрипт остановлен'
  \quit
\endif

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;   -- crypt(), gen_salt()

-- ======================= 1. Роли и права доступа =======================
-- Повторный запуск: удалить роли этого проекта вместе с их правами.
DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['cafe_admin_ivanova', 'cafe_manager_petrov', 'cafe_web', 'cafe_backup',
                             'cafe_admin', 'cafe_manager', 'cafe_guest'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('DROP OWNED BY %I', r);
            EXECUTE format('DROP ROLE %I', r);
        END IF;
    END LOOP;
END $$;

-- Групповые роли (без входа) — соответствуют ролям предметной области
CREATE ROLE cafe_admin   NOLOGIN;   -- администратор: справочники, пользователи, все брони
CREATE ROLE cafe_manager NOLOGIN;   -- менеджер: гости и брони, смена статуса
CREATE ROLE cafe_guest   NOLOGIN;   -- гость (сайт): только просмотр залов и бронирование через функции
-- Учётные записи входа; пароли хранятся в PostgreSQL как SCRAM-SHA-256
SET password_encryption = 'scram-sha-256';
CREATE ROLE cafe_admin_ivanova  LOGIN PASSWORD :'admin_pw'   IN ROLE cafe_admin;
CREATE ROLE cafe_manager_petrov LOGIN PASSWORD :'manager_pw' IN ROLE cafe_manager;
CREATE ROLE cafe_web            LOGIN PASSWORD :'web_pw'     IN ROLE cafe_guest CONNECTION LIMIT 20;
-- Резервное копирование: только чтение всех данных (встроенная роль pg_read_all_data)
CREATE ROLE cafe_backup         LOGIN PASSWORD :'backup_pw'  IN ROLE pg_read_all_data;

-- По умолчанию запретить всё всем, затем выдать необходимое
DO $$ BEGIN
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO cafe_admin, cafe_manager, cafe_guest, cafe_backup',
                   current_database());
END $$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA cafe FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cafe FROM PUBLIC;
GRANT USAGE ON SCHEMA cafe TO cafe_admin, cafe_manager, cafe_guest;

SET search_path = cafe;

-- Администратор: справочники и брони полностью; пользователи — без доступа к хешу пароля
GRANT SELECT, INSERT, UPDATE, DELETE ON roles, halls, cafe_tables, guests, bookings TO cafe_admin;
GRANT SELECT (id, login, full_name, role_id), INSERT (login, full_name, role_id),
      UPDATE (login, full_name, role_id), DELETE ON users TO cafe_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA cafe TO cafe_admin;

-- Менеджер: просмотр залов и столиков, работа с гостями и бронями без удаления
GRANT SELECT ON halls, cafe_tables, guests, bookings TO cafe_manager;
GRANT SELECT (id, login, full_name, role_id) ON users TO cafe_manager;
GRANT INSERT ON guests, bookings TO cafe_manager;
GRANT UPDATE (full_name, email) ON guests TO cafe_manager;
GRANT UPDATE (status) ON bookings TO cafe_manager;
GRANT USAGE ON SEQUENCE guests_id_seq, bookings_id_seq TO cafe_manager;

-- Гость (сайт): только залы и столики; персональные данные гостей и брони недоступны
GRANT SELECT ON halls, cafe_tables TO cafe_guest;

-- ======================= 2. Хеширование паролей =======================
-- В users.password_hash хранится только bcrypt-хеш (соль внутри хеша, 2^10 раундов)
-- или «!» — вход запрещён. Открытый пароль в базе не хранится.
ALTER TABLE users ALTER COLUMN password_hash SET DEFAULT '!';
ALTER TABLE users ADD CONSTRAINT ck_users_password_bcrypt
    CHECK (password_hash = '!' OR password_hash ~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$');

CREATE FUNCTION set_password(p_login text, p_password text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF NOT pg_has_role(session_user, 'cafe_admin', 'MEMBER') THEN
        RAISE EXCEPTION 'Задавать пароли может только администратор' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF length(p_password) < 8 OR p_password !~ '[0-9]' OR p_password !~ '[A-Za-zА-Яа-яЁё]' THEN
        RAISE EXCEPTION 'Пароль должен быть не короче 8 символов и содержать буквы и цифры'
            USING ERRCODE = 'check_violation';
    END IF;
    UPDATE cafe.users SET password_hash = public.crypt(p_password, public.gen_salt('bf', 10))
    WHERE login = p_login;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Пользователь % не найден', p_login USING ERRCODE = 'no_data_found';
    END IF;
END $$;
COMMENT ON FUNCTION set_password IS 'Задать пароль пользователю (только администратор); хранится bcrypt-хеш';

CREATE FUNCTION check_password(p_login text, p_password text)
RETURNS TABLE (user_id integer, full_name varchar, role_name varchar)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    h text;
BEGIN
    SELECT u.password_hash INTO h FROM cafe.users u WHERE u.login = p_login;
    -- для несуществующего логина хеш всё равно считается: время ответа не выдаёт, есть ли логин
    IF h IS NULL OR h = '!' THEN
        PERFORM public.crypt(coalesce(p_password, ''), public.gen_salt('bf', 10));
        RETURN;
    END IF;
    RETURN QUERY
        SELECT u.id, u.full_name, r.name FROM cafe.users u JOIN cafe.roles r ON r.id = u.role_id
        WHERE u.login = p_login AND u.password_hash = public.crypt(p_password, h);
END $$;
COMMENT ON FUNCTION check_password IS 'Проверка логина и пароля; при ошибке возвращает пустой результат';

-- ======================= 3. Функции для сайта (статический SQL с параметрами) =======================
-- Параметры функций PL/pgSQL передаются в запрос как значения, а не как текст SQL,
-- поэтому ввод вроде «' OR '1'='1» не может изменить запрос.
CREATE FUNCTION free_tables(p_date date, p_start time, p_end time, p_guests integer)
RETURNS TABLE (table_id integer, hall varchar, number smallint, capacity smallint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
    SELECT t.id, h.name, t.number, t.capacity
    FROM cafe.cafe_tables t JOIN cafe.halls h ON h.id = t.hall_id
    WHERE t.capacity >= p_guests
      AND NOT EXISTS (SELECT 1 FROM cafe.bookings b
                      WHERE b.table_id = t.id AND b.booking_date = p_date
                        AND b.status IN ('new', 'confirmed')
                        AND b.time_start < p_end AND p_start < b.time_end)
    ORDER BY h.id, t.number
$$;

CREATE FUNCTION create_booking(p_name text, p_phone text, p_email text, p_table_id integer,
                               p_date date, p_start time, p_end time, p_guests integer)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    v_guest integer;
    v_id bigint;
BEGIN
    IF p_date < current_date THEN
        RAISE EXCEPTION 'Нельзя забронировать столик на прошедшую дату' USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO cafe.guests (full_name, phone, email) VALUES (p_name, p_phone, nullif(p_email, ''))
    ON CONFLICT (phone) DO UPDATE
        SET full_name = EXCLUDED.full_name, email = coalesce(EXCLUDED.email, cafe.guests.email)
    RETURNING id INTO v_guest;
    INSERT INTO cafe.bookings (guest_id, table_id, user_id, booking_date, time_start, time_end, guests_count)
    VALUES (v_guest, p_table_id, (SELECT id FROM cafe.users WHERE login = 'site'),
            p_date, p_start, p_end, p_guests)
    RETURNING id INTO v_id;
    RETURN v_id;
END $$;
COMMENT ON FUNCTION create_booking IS 'Бронирование с сайта: гость ищется по телефону, бронь в статусе new';

-- Функции по умолчанию доступны всем — закрыть и выдать явно
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA cafe FROM PUBLIC;
GRANT EXECUTE ON FUNCTION set_password(text, text) TO cafe_admin;
GRANT EXECUTE ON FUNCTION check_password(text, text) TO cafe_admin, cafe_manager, cafe_guest;
GRANT EXECUTE ON FUNCTION free_tables(date, time, time, integer) TO cafe_admin, cafe_manager, cafe_guest;
GRANT EXECUTE ON FUNCTION create_booking(text, text, text, integer, date, time, time, integer)
    TO cafe_admin, cafe_manager, cafe_guest;

-- ======================= 4. Журнал аудита =======================
CREATE TABLE audit_log (
    id          bigint      GENERATED ALWAYS AS IDENTITY,
    changed_at  timestamptz NOT NULL DEFAULT now(),
    db_user     text        NOT NULL DEFAULT session_user,   -- кто вошёл в базу
    operation   varchar(6)  NOT NULL,
    table_name  text        NOT NULL,
    row_id      bigint,
    old_data    jsonb,
    new_data    jsonb,
    CONSTRAINT pk_audit_log PRIMARY KEY (id),
    CONSTRAINT ck_audit_log_operation CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'))
);
CREATE INDEX ix_audit_log_table_row ON audit_log (table_name, row_id);
CREATE INDEX ix_audit_log_changed_at ON audit_log (changed_at);
COMMENT ON TABLE audit_log IS 'Журнал изменений: кто, когда, что было и что стало';

CREATE FUNCTION audit_trigger() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    o jsonb := CASE WHEN TG_OP <> 'INSERT' THEN to_jsonb(OLD) END;
    n jsonb := CASE WHEN TG_OP <> 'DELETE' THEN to_jsonb(NEW) END;
BEGIN
    IF TG_OP = 'UPDATE' AND o = n THEN
        RETURN NULL;                                   -- ничего не изменилось
    END IF;
    IF TG_TABLE_NAME = 'users' THEN                    -- хеш пароля в журнал не пишется
        IF o ? 'password_hash' THEN o := o || '{"password_hash": "***"}'; END IF;
        IF n ? 'password_hash' THEN
            n := n || jsonb_build_object('password_hash',
                 CASE WHEN TG_OP = 'UPDATE' AND OLD.password_hash IS DISTINCT FROM NEW.password_hash
                      THEN '*** (изменён)' ELSE '***' END);
        END IF;
    END IF;
    INSERT INTO cafe.audit_log (operation, table_name, row_id, old_data, new_data)
    VALUES (TG_OP, TG_TABLE_NAME, (coalesce(n, o) ->> 'id')::bigint, o, n);
    RETURN NULL;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['roles', 'users', 'guests', 'halls', 'cafe_tables', 'bookings'] LOOP
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON cafe.%I '
                       'FOR EACH ROW EXECUTE FUNCTION cafe.audit_trigger()', t, t);
    END LOOP;
END $$;

-- Журнал нельзя изменить или очистить никому, включая владельца
CREATE FUNCTION audit_log_readonly() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    RAISE EXCEPTION 'Журнал аудита нельзя изменять или удалять' USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER trg_audit_log_readonly BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_readonly();
CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_readonly();

REVOKE ALL ON audit_log FROM PUBLIC;
GRANT SELECT ON audit_log TO cafe_admin;               -- только чтение и только администратору
REVOKE EXECUTE ON FUNCTION audit_trigger(), audit_log_readonly() FROM PUBLIC;
