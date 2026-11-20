#!/usr/bin/env bash
# ПП.02, этап 7. Резервное копирование базы cafe_booking.
# Выполняется от роли cafe_backup (только чтение: pg_read_all_data).
# Пароль — в переменной PGPASSWORD или в файле ~/.pgpass (права 600), не в скрипте.
#   PGUSER=cafe_backup ./backup.sh            # по расписанию: cron, ежедневно в 03:00
set -euo pipefail
DB="${CAFE_DB:-cafe_booking}"
DIR="${BACKUP_DIR:-$(dirname "$0")/backups}"
KEEP="${BACKUP_KEEP:-7}"                       # сколько последних копий хранить
umask 077                                      # копии доступны только владельцу
mkdir -p "$DIR"
FILE="$DIR/${DB}_$(date +%Y%m%d_%H%M%S).dump"
pg_dump --format=custom --compress=9 --dbname="$DB" --file="$FILE"
(cd "$DIR" && sha256sum "$(basename "$FILE")" > "$(basename "$FILE").sha256")
pg_restore --list "$FILE" > /dev/null          # архив читается
ls -1t "$DIR"/"${DB}"_*.dump | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f -- "$old" "$old.sha256"              # ротация: старые копии удаляются
done
echo "$FILE"
