# VoinovDmitrii-PP.02-PP.11

Производственная практика, студент Войнов Д.А., группа 3ИП-7-24.

## Темы
- **ПП.02** — Разработка защищенной базы данных системы бронирования столиков в кафе.
- **ПП.11** — Разработка модуля заказа столиков в кафе с пересылкой данных о брони в группу администраторов ВКонтакте.

## Структура
- `PP.02/week1/` — анализ предметной области, ER-диаграмма (`er_diagram.png`, исходник `er.dot`), нормализация (`analysis.md`), отчёт (`report_week1.docx`).
- `PP.02/week2/` — неделя 2 = этап 6 (ПП.02): SQL-скрипт базы данных на PostgreSQL (`01_schema.sql` — таблицы, ключи, ограничения, индексы; `02_test_data.sql` — тестовые данные), проверка (`check_db.sql`, `check_output.txt`), схема таблиц (`schema.png`), отчёт (`report_week2.docx`).
- `PP.02/week3/` — неделя 3 = этап 7 (ПП.02): защита БД (`03_security.sql` — роли и права, bcrypt-хеши паролей, функции со статическим SQL, журнал аудита), резервное копирование (`backup.sh`, `restore_check.sh`), демонстрации (`demo_security.py`, `sql_injection_demo.py`, `*_output.txt`, `screens/`), отчёт (`report_week3.docx`).
- `PP.02/week4/` — неделя 4 = этап 8 (ПП.02): триггеры и представления (`04_logic.sql` — запрет двойной брони столика, проверка вместимости, `v_bookings`, `v_hall_load`), демонстрация (`demo_logic.sql`, `demo_logic_output.txt`, `screens/`), автотесты прав и ограничений (`tests/`, `tests_output.txt`), итоговый отчёт по ПП.02 (`final_pp02.md`, `report_pp02_final.docx`).
- `PP.11/stage1/` — этап 1 (ПП.11): сценарий бронирования, макеты страниц (`mockups/`), изучение VK API и схема интеграции (`analysis.md`, `vk_scheme.png`), отчёт (`report_stage1.docx`).
- `PP.11/app/` — бэкенд модуля бронирования на Flask (этап 2): API свободных столиков, создания и отмены брони с проверкой пересечений; рабочий черновик таблиц `schema_draft.sql` по модели этапа 5.
- `PP.11/stage2/` — этап 2 (ПП.11): описание бэкенда (`backend.md`), вывод проверки API (`api_demo.txt`), отчёт (`report_stage2.docx`).
- `PP.11/app/static/`, `vk.py`, `vk_bot.py`, `tests/` — этап 3: веб-форма брони со схемой зала, пересылка брони в беседу администраторов ВКонтакте с кнопками «Подтвердить»/«Отклонить», модульные тесты.
- `PP.11/stage3/` — этап 3 (ПП.11): описание (`frontend_vk.md`), снимки экрана (`screens/`), вывод тестов (`tests_output.txt`) и проверки в ВК (`vk_demo.txt`), отчёт (`report_stage3.docx`).
- `PP.11/stage4/` — этап 4 (ПП.11): тестирование всего сценария и обработка ошибок (`testing.md`, `tests_output.txt`, `errors_demo.txt`, `screens/`), блок-схемы по коду (`flowcharts/`), отчёт по этапу 4 (`report_stage4.docx`) и итоговый отчёт по ПП.11 (`final_pp11.md`, `report_pp11_final.docx`).

## Запуск бэкенда
```
cd PP.11/app
pip install -r requirements.txt
python app.py   # http://127.0.0.1:5000
```

## Пересылка в ВКонтакте (этап 3)
```
cd PP.11/app
cp .env.example .env          # вписать VK_TOKEN, VK_GROUP_ID, VK_PEER_ID; .env не коммитится
set -a; . ./.env; set +a
python app.py                 # веб-форма и API
python vk_bot.py              # обработка кнопок «Подтвердить»/«Отклонить»
python -m pytest -v tests     # 79 тестов, VK API заменён заглушкой (этап 4)
```

## База данных ПП.02 (PostgreSQL 15+)
```
cd PP.02
createdb cafe_booking
psql -d cafe_booking -v ON_ERROR_STOP=1 -f week2/01_schema.sql -f week2/02_test_data.sql
# этап 7: пароли ролей СУБД только через окружение, в репозиторий не попадают
export CAFE_ADMIN_DB_PASSWORD=... CAFE_MANAGER_DB_PASSWORD=... CAFE_WEB_DB_PASSWORD=... CAFE_BACKUP_DB_PASSWORD=...
psql -d cafe_booking -v ON_ERROR_STOP=1 -f week3/03_security.sql
# этап 8: триггеры и представления, затем 88 автотестов на отдельной базе cafe_booking_test
psql -d cafe_booking -v ON_ERROR_STOP=1 -f week4/04_logic.sql
cd week4 && pip install pytest psycopg2-binary && python -m pytest -v tests
```
