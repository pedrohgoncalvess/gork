from pathlib import Path

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

    backend = get_backend(_migration_database_url())
    migrations = read_migrations(str(migrations_path))
    if not migrations:
        raise RuntimeError(f"No migrations found in: {migrations_path}")

    # Gunicorn starts more than one worker. Yoyo's database lock serializes
    # workers so only the first one applies changes and the rest see no work.
    with backend.lock():
        pending = backend.to_apply(migrations)
        backend.apply_migrations(pending)

    return len(pending)
