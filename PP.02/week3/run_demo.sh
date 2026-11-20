#!/usr/bin/env bash
# ПП.02, этап 7. Пересоздать базу, применить защиту и выполнить все демонстрации.
# Нужны: PGHOST, PGPORT, PGUSER/PGPASSWORD суперпользователя и пароли ролей
# CAFE_ADMIN_DB_PASSWORD, CAFE_MANAGER_DB_PASSWORD, CAFE_WEB_DB_PASSWORD, CAFE_BACKUP_DB_PASSWORD.
set -euo pipefail
cd "$(dirname "$0")"
dropdb --if-exists cafe_booking && createdb cafe_booking
psql -q -d cafe_booking -v ON_ERROR_STOP=1 -f ../week2/01_schema.sql -f ../week2/02_test_data.sql -f 03_security.sql
python3 demo_security.py > demo_output.txt
python3 sql_injection_demo.py > injection_output.txt
F=$(PGUSER=cafe_backup PGPASSWORD="$CAFE_BACKUP_DB_PASSWORD" ./backup.sh)
./restore_check.sh "$F"
