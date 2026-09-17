import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from database.migrate import _migration_database_url, apply_pending_migrations


class MigrationRunnerTests(unittest.TestCase):
    def test_database_url_uses_runtime_pg_variables_and_escapes_credentials(self):
        values = {
            "PG_USER": "admin",
            "PG_PASSWORD": "p@ss/word",
            "PG_HOST": "postgres",
            "PG_PORT": "5432",
            "PG_NAME": "gork",
        }

        with patch("database.migrate.get_env_var", side_effect=values.get):
            url = _migration_database_url()

        self.assertEqual(
            url,
            "postgresql+psycopg://admin:p%40ss%2Fword@postgres:5432/gork",
        )

    def test_missing_database_configuration_aborts_startup(self):
        with patch("database.migrate.get_env_var", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "PG_USER"):
                _migration_database_url()

    def test_pending_migrations_are_applied_under_database_lock(self):
        pending = [Mock(), Mock()]
        backend = Mock()
        backend.lock.return_value = nullcontext()
        backend.to_apply.return_value = pending
        migrations = [Mock(), Mock(), Mock()]

        with (
            patch("database.migrate._migration_database_url", return_value="postgresql://db"),
            patch("database.migrate.get_backend", return_value=backend) as get_backend,
            patch("database.migrate.read_migrations", return_value=migrations) as read_migrations,
        ):
            applied = apply_pending_migrations()

        self.assertEqual(applied, 2)
        get_backend.assert_called_once_with("postgresql://db")
        read_migrations.assert_called_once()
        backend.to_apply.assert_called_once_with(migrations)
        backend.apply_migrations.assert_called_once_with(pending)

    def test_empty_migration_source_aborts_startup(self):
        backend = Mock()

        with (
            patch("database.migrate._migration_database_url", return_value="postgresql://db"),
            patch("database.migrate.get_backend", return_value=backend),
            patch("database.migrate.read_migrations", return_value=[]),
        ):
            with self.assertRaisesRegex(RuntimeError, "No migrations found"):
                apply_pending_migrations()

        backend.apply_migrations.assert_not_called()


if __name__ == "__main__":
    unittest.main()
