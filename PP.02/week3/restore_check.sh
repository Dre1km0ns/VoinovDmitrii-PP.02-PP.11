#!/usr/bin/env bash
# ПП.02, этап 7. Проверка резервной копии: восстановление в отдельную базу
# и сравнение количества строк с рабочей базой. Выполняется администратором СУБД.
#   ./restore_check.sh backups/cafe_booking_YYYYMMDD_HHMMSS.dump
set -euo pipefail
FILE="$1"; SRC="${CAFE_DB:-cafe_booking}"; CHECK="${SRC}_restore_check"
(cd "$(dirname "$FILE")" && sha256sum --check --quiet "$(basename "$FILE").sha256")
echo "Контрольная сумма совпадает"
dropdb --if-exists "$CHECK"
createdb "$CHECK"
pg_restore --exit-on-error --dbname="$CHECK" "$FILE"
Q="SELECT string_agg(t || '=' || n, ' ' ORDER BY t) FROM (
   SELECT 'roles' t, count(*) n FROM cafe.roles UNION ALL SELECT 'users', count(*) FROM cafe.users
   UNION ALL SELECT 'guests', count(*) FROM cafe.guests UNION ALL SELECT 'halls', count(*) FROM cafe.halls
   UNION ALL SELECT 'cafe_tables', count(*) FROM cafe.cafe_tables
   UNION ALL SELECT 'bookings', count(*) FROM cafe.bookings
   UNION ALL SELECT 'audit_log', count(*) FROM cafe.audit_log) s"
A=$(psql -qAt -d "$SRC" -c "$Q"); B=$(psql -qAt -d "$CHECK" -c "$Q")
echo "рабочая база:        $A"
echo "восстановленная база: $B"
dropdb "$CHECK"
[ "$A" = "$B" ] && echo "Восстановление проверено: данные совпадают" || { echo "РАСХОЖДЕНИЕ"; exit 1; }
