"""Фикстуры тестов базы данных (ПП.02, этап 8).

Перед тестами создаётся отдельная база (по умолчанию cafe_booking_test), в неё
выполняются скрипты недель 2–4. Пароли ролей СУБД берутся из CAFE_*_DB_PASSWORD, а если их нет — генерируются
случайно на время запуска. Подключение суперпользователя — из PGHOST, PGPORT, PGUSER, PGPASSWORD.
    cd PP.02/week4 && python -m pytest -v tests
"""
import os
import secrets
import subprocess
from pathlib import Path

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[2]          # PP.02
SCRIPTS = [ROOT / "week2/01_schema.sql", ROOT / "week2/02_test_data.sql",
           ROOT / "week3/03_security.sql", ROOT / "week4/04_logic.sql"]
DB = os.environ.get("CAFE_TEST_DB", "cafe_booking_test")
LOGINS = {"admin": ("cafe_admin_ivanova", "CAFE_ADMIN_DB_PASSWORD"),
          "manager": ("cafe_manager_petrov", "CAFE_MANAGER_DB_PASSWORD"),
          "web": ("cafe_web", "CAFE_WEB_DB_PASSWORD"),
          "backup": ("cafe_backup", "CAFE_BACKUP_DB_PASSWORD")}


@pytest.fixture(scope="session")
def database():
    env = dict(os.environ)
    for _, var in LOGINS.values():           # роли общие для кластера: если пароли
        env.setdefault(var, secrets.token_urlsafe(16))   # уже заданы, они сохраняются
    subprocess.run(["dropdb", "--if-exists", DB], env=env, check=True, capture_output=True)
    subprocess.run(["createdb", DB], env=env, check=True)
    cmd = ["psql", "-q", "-d", DB, "-v", "ON_ERROR_STOP=1"]
    for s in SCRIPTS:
        cmd += ["-f", str(s)]
    subprocess.run(cmd, env=env, check=True)
    yield env
    subprocess.run(["dropdb", "--if-exists", DB], env=env, check=False)


def _connect(env, who):
    common = dict(host=env.get("PGHOST", "127.0.0.1"), port=env.get("PGPORT", "5432"), dbname=DB)
    if who == "owner":
        return psycopg2.connect(user=env.get("PGUSER", "postgres"), password=env.get("PGPASSWORD"), **common)
    user, var = LOGINS[who]
    return psycopg2.connect(user=user, password=env[var], **common)


@pytest.fixture(scope="session")
def connect(database):
    """connect(who) — новое подключение под ролью owner/admin/manager/web/backup."""
    opened = []

    def make(who):
        c = _connect(database, who)
        opened.append(c)
        return c
    yield make
    for c in opened:
        c.close()


@pytest.fixture
def db(database):
    """Подключения ролей; после теста все изменения откатываются, подключения закрываются."""
    conns = {who: _connect(database, who) for who in ("owner", "admin", "manager", "web")}
    yield conns
    for c in conns.values():
        c.rollback()
        c.close()


def run(conn, sql, params=None):
    """Выполнить запрос в точке сохранения: ошибка не ломает транзакцию теста."""
    cur = conn.cursor()
    cur.execute("SAVEPOINT t")
    try:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else cur.rowcount
        cur.execute("RELEASE SAVEPOINT t")
        return rows
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT t")
        raise
