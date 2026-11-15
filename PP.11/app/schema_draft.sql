-- Рабочий черновик таблиц для API бронирования (ПП.11, этап 2).
-- Построен по модели этапа 5 (PP.02/week1: ER-диаграмма, 3НФ).
-- Это НЕ официальный SQL-скрипт ПП.02: полный скрипт с ограничениями,
-- индексами и тестовыми данными — этап 6, защита БД — этапы 7–8.

CREATE TABLE IF NOT EXISTS roles (          -- Роли
    id    INTEGER PRIMARY KEY,              -- id_роли
    name  TEXT NOT NULL UNIQUE              -- название
);

CREATE TABLE IF NOT EXISTS users (          -- Пользователи
    id             INTEGER PRIMARY KEY,     -- id_пользователя
    login          TEXT NOT NULL UNIQUE,    -- логин
    password_hash  TEXT NOT NULL,           -- хеш_пароля (хеширование — этап 7)
    full_name      TEXT NOT NULL,           -- фио
    role_id        INTEGER NOT NULL REFERENCES roles(id)   -- id_роли
);

CREATE TABLE IF NOT EXISTS guests (         -- Гости
    id         INTEGER PRIMARY KEY,         -- id_гостя
    full_name  TEXT NOT NULL,               -- фио
    phone      TEXT NOT NULL UNIQUE,        -- телефон
    email      TEXT                         -- email
);

CREATE TABLE IF NOT EXISTS halls (          -- Залы
    id           INTEGER PRIMARY KEY,       -- id_зала
    name         TEXT NOT NULL UNIQUE,      -- название
    description  TEXT                       -- описание
);

CREATE TABLE IF NOT EXISTS cafe_tables (    -- Столики
    id        INTEGER PRIMARY KEY,          -- id_столика
    hall_id   INTEGER NOT NULL REFERENCES halls(id),   -- id_зала
    number    INTEGER NOT NULL,             -- номер
    capacity  INTEGER NOT NULL,             -- вместимость
    UNIQUE (hall_id, number)
);

CREATE TABLE IF NOT EXISTS bookings (       -- Брони
    id          INTEGER PRIMARY KEY,        -- id_брони
    guest_id    INTEGER NOT NULL REFERENCES guests(id),       -- id_гостя
    table_id    INTEGER NOT NULL REFERENCES cafe_tables(id),  -- id_столика
    user_id     INTEGER NOT NULL REFERENCES users(id),        -- id_пользователя
    date        TEXT NOT NULL,              -- дата (YYYY-MM-DD)
    time_start  TEXT NOT NULL,              -- время_начала (HH:MM)
    time_end    TEXT NOT NULL,              -- время_окончания (HH:MM)
    guests_count INTEGER NOT NULL,          -- кол_во_гостей
    status      TEXT NOT NULL DEFAULT 'new',-- статус: new / confirmed / rejected / cancelled
    created_at  TEXT NOT NULL               -- создана
);
