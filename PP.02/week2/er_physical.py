"""Схема таблиц (физическая модель) строится по системному каталогу созданной базы.
Запуск: PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=... python er_physical.py"""
import subprocess
import psycopg2

conn = psycopg2.connect(dbname="cafe_booking")
cur = conn.cursor()
cur.execute("""
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.attnum
FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
WHERE c.relnamespace = 'cafe'::regnamespace AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
  AND c.relname IN ('roles','users','guests','halls','cafe_tables','bookings')
ORDER BY c.relname, a.attnum""")
cols = {}
for t, col, typ, nn, _ in cur.fetchall():
    cols.setdefault(t, []).append((col, typ, nn))
cur.execute("""
SELECT conrelid::regclass::text, contype, conkey, confrelid::regclass::text
FROM pg_constraint WHERE connamespace = 'cafe'::regnamespace AND contype IN ('p','u','f')""")
marks, fks = {}, []
for rel, typ, keys, ref in cur.fetchall():
    rel = rel.replace("cafe.", "")
    for k in keys:
        cur.execute("SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum = %s",
                    ("cafe." + rel, k))
        name = cur.fetchone()[0]
        marks.setdefault((rel, name), set()).add({"p": "PK", "u": "UQ", "f": "FK"}[typ])
    if typ == "f":
        fks.append((ref.replace("cafe.", ""), rel))
order = ["roles", "users", "guests", "halls", "cafe_tables", "bookings"]
out = ['digraph S {', ' graph [rankdir=LR, fontname="DejaVu Sans", nodesep=0.5, ranksep=1.1, dpi=150];',
       ' node [shape=plaintext, fontname="DejaVu Sans", fontsize=11];',
       ' edge [arrowhead=crowodot, arrowtail=teetee, dir=both, color="#444444"];']
for t in order:
    rows = "".join(
        f'<tr><td align="left">{" ".join(sorted(marks.get((t, c), [])))}</td>'
        f'<td align="left">{"<b>" + c + "</b>" if "PK" in marks.get((t, c), set()) else c}</td>'
        f'<td align="left">{typ}{"" if nn else " NULL"}</td></tr>' for c, typ, nn in cols[t])
    color = "#f9cb9c" if t == "bookings" else "#cfe2f3"
    out.append(f' {t} [label=<<table border="1" cellborder="0" cellspacing="0" cellpadding="3">'
               f'<tr><td colspan="3" bgcolor="{color}"><b>cafe.{t}</b></td></tr>{rows}</table>>];')
for a, b in sorted(set(fks)):
    out.append(f" {a} -> {b};")
out.append("}")
open("schema.dot", "w").write("\n".join(out))
subprocess.run(["dot", "-Tpng", "schema.dot", "-o", "schema.png"], check=True)
print("schema.png:", len(cols), "таблиц,", len(set(fks)), "внешних ключей")
