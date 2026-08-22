import asyncio
import unittest
from unittest.mock import patch

from database.connection import PgConnection


class _FakeSession:
    def __init__(self):
        self.close_started = asyncio.Event()
        self.allow_close = asyncio.Event()
        self.rollback_calls = 0
        self.close_calls = 0

    def in_transaction(self):
        return True

    async def rollback(self):
        self.rollback_calls += 1

    async def close(self):
        self.close_started.set()
        await self.allow_close.wait()
        self.close_calls += 1


class _FakeFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = _FakeSession()
        self.sessions.append(session)
        return session


class DatabaseConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_during_connect_closes_created_session(self):
        factory = _FakeFactory()
        log_started = asyncio.Event()

        async def blocked_log(*args):
            if args[-1] == "New SQLAlchemy Session":
                log_started.set()
                await asyncio.Event().wait()

        with (
            patch("database.connection.get_session_factory", return_value=factory),
            patch("database.connection.logger.info", side_effect=blocked_log),
        ):
            connect_task = asyncio.create_task(PgConnection().connect())
            await log_started.wait()
            session = factory.sessions[0]
            session.allow_close.set()
            connect_task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await connect_task

        self.assertEqual(1, session.close_calls)

    async def test_nested_connections_in_same_task_reuse_session(self):
        factory = _FakeFactory()

        with patch("database.connection.get_session_factory", return_value=factory):
            async with PgConnection() as outer:
                outer.allow_close.set()
                async with PgConnection() as inner:
                    self.assertIs(inner, outer)

        self.assertEqual(1, len(factory.sessions))
        self.assertEqual(1, outer.close_calls)
        self.assertEqual(1, outer.rollback_calls)

    async def test_concurrent_tasks_do_not_share_session(self):
        factory = _FakeFactory()
        ready = asyncio.Event()
        entered = 0

        async def use_connection():
            nonlocal entered
            async with PgConnection() as session:
                session.allow_close.set()
                entered += 1
                if entered == 2:
                    ready.set()
                await ready.wait()
                return session

        with patch("database.connection.get_session_factory", return_value=factory):
            first, second = await asyncio.gather(use_connection(), use_connection())

        self.assertIsNot(first, second)
        self.assertEqual(2, len(factory.sessions))

    async def test_cancellation_waits_for_connection_cleanup(self):
        factory = _FakeFactory()

        with patch("database.connection.get_session_factory", return_value=factory):
            connection = PgConnection()
            await connection.connect()
            session = connection.session

            close_task = asyncio.create_task(connection.close())
            await session.close_started.wait()
            close_task.cancel()
            await asyncio.sleep(0)

            self.assertFalse(close_task.done())
            session.allow_close.set()

            with self.assertRaises(asyncio.CancelledError):
                await close_task

        self.assertEqual(1, session.close_calls)
        self.assertIsNone(connection.session)


if __name__ == "__main__":
    unittest.main()
