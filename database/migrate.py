from pathlib import Path

import psycopg
from sqlalchemy.engine import URL
from yoyo import get_backend, read_migrations

from utils import get_env_var, project_root


_REQUIRED_DATABASE_VARIABLES = (
    "PG_USER",
    "PG_PASSWORD",
    "PG_HOST",
    "PG_PORT",
    "PG_NAME",
)

# Stable across workers and containers; released when the connection closes.
_MIGRATION_LOCK_ID = 0x676F726B6D696772


def _migration_database_url() -> str:
    values = {name: get_env_var(name) for name in _REQUIRED_DATABASE_VARIABLES}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing database variables required for migrations: "
            + ", ".join(missing)
        )

    url = URL.create(
        drivername="postgresql+psycopg",
        username=values["PG_USER"],
        password=values["PG_PASSWORD"],
        host=values["PG_HOST"],
        port=int(values["PG_PORT"]),
        database=values["PG_NAME"],
    )
    return url.render_as_string(hide_password=False)


def apply_pending_migrations() -> int:
    """Apply every pending Yoyo migration before the application starts."""
    migrations_path = Path(project_root) / "database" / "migrations"
    if not migrations_path.is_dir():
        raise RuntimeError(f"Migration directory not found: {migrations_path}")

    migrations = read_migrations(str(migrations_path))
    if not migrations:
        raise RuntimeError(f"No migrations found in: {migrations_path}")

    database_url = _migration_database_url()
    conninfo = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    # Yoyo's lock depends on a table that may not exist on the first startup.
    # Serialize bootstrap as well as migrations, including across containers.
    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_ID,))
        # Yoyo suppresses every DatabaseError while creating this table. Create
        # it explicitly so permission/schema errors reach the startup log.
        connection.execute(
            'CREATE TABLE IF NOT EXISTS "yoyo_lock" ('
            '"locked" INT DEFAULT 1 PRIMARY KEY, '
            '"ctime" TIMESTAMP, "pid" INT NOT NULL)'
        )
        with get_backend(database_url) as backend:
            with backend.lock():
                pending = backend.to_apply(migrations)
                backend.apply_migrations(pending)

    return len(pending)
