import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, Mock, patch

import psycopg

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
        backend_context = MagicMock()
        backend_context.__enter__.return_value = backend
        backend.lock.return_value = nullcontext()
        backend.to_apply.return_value = pending
        migrations = [Mock(), Mock(), Mock()]
        connection = Mock()
        events = Mock()
        events.attach_mock(connection.execute, "execute")

        with (
            patch("database.migrate._migration_database_url", return_value="postgresql://db"),
            patch("database.migrate.psycopg.connect") as connect,
            patch("database.migrate.get_backend", return_value=backend_context) as get_backend,
            patch("database.migrate.read_migrations", return_value=migrations) as read_migrations,
        ):
            connect.return_value.__enter__.return_value = connection
            events.attach_mock(get_backend, "get_backend")
            applied = apply_pending_migrations()

        self.assertEqual(applied, 2)
        get_backend.assert_called_once_with("postgresql://db")
        read_migrations.assert_called_once()
        backend.to_apply.assert_called_once_with(migrations)
        backend.apply_migrations.assert_called_once_with(pending)
        self.assertIn("pg_advisory_lock", events.mock_calls[0].args[0])
        self.assertIn('CREATE TABLE IF NOT EXISTS "yoyo_lock"', events.mock_calls[1].args[0])
        self.assertEqual(events.mock_calls[2][0], "get_backend")
        backend_context.__exit__.assert_called_once()
        connect.return_value.__exit__.assert_called_once()

    def test_bootstrap_failure_preserves_database_error_and_closes_connection(self):
        error = psycopg.errors.InsufficientPrivilege("permission denied for schema public")
        with (
            patch("database.migrate._migration_database_url", return_value="postgresql+psycopg://db"),
            patch("database.migrate.psycopg.connect") as connect,
            patch("database.migrate.get_backend") as get_backend,
            patch("database.migrate.read_migrations", return_value=[Mock()]),
        ):
            connection = connect.return_value.__enter__.return_value
            connection.execute.side_effect = [None, error]
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                apply_pending_migrations()

        connect.assert_called_once_with("postgresql://db", autocommit=True)
        get_backend.assert_not_called()
        connect.return_value.__exit__.assert_called_once()

    def test_migration_failure_closes_backend_and_releases_bootstrap_lock(self):
        with (
            patch("database.migrate._migration_database_url", return_value="postgresql://db"),
            patch("database.migrate.psycopg.connect") as connect,
            patch("database.migrate.get_backend") as get_backend,
            patch("database.migrate.read_migrations", return_value=[Mock()]),
        ):
            backend = get_backend.return_value.__enter__.return_value
            backend.lock.return_value = nullcontext()
            backend.apply_migrations.side_effect = RuntimeError("migration failed")
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                apply_pending_migrations()

        get_backend.return_value.__exit__.assert_called_once()
        connect.return_value.__exit__.assert_called_once()

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
