"""
Async SQLAlchemy Database Connection Wrapper

Provides an async SQLAlchemy session manager using context manager semantics.
Automatically loads PostgreSQL credentials from environment variables and
initializes an async engine with SQLAlchemy 2.0 style.
"""
import asyncio
import sys
from contextvars import ContextVar, Token
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    AsyncSession,
    create_async_engine,
)

from log import logger
from utils import get_env_var


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


@dataclass
class _SessionScope:
    session: AsyncSession
    task: asyncio.Task | None
    active: bool = True


_current_session_scope: ContextVar[_SessionScope | None] = ContextVar(
    "current_database_session_scope",
    default=None,
)


def _database_url() -> str:
    user = get_env_var("PG_USER")
    password = get_env_var("PG_PASSWORD")
    host = get_env_var("PG_HOST")
    port = get_env_var("PG_PORT")
    db = get_env_var("PG_NAME")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory

    if _session_factory is None:
        pool_size = int(get_env_var("PG_POOL_SIZE") or 3)
        max_overflow = int(get_env_var("PG_MAX_OVERFLOW") or 5)
        _engine = create_async_engine(
            _database_url(),
            echo=False,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=15,
            pool_pre_ping=True,
            future=True
        )
        _session_factory = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    return _session_factory


async def dispose_database_engine() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


class PgConnection:
    def __init__(self):
        self.session: AsyncSession | None = None
        self._owns_session = False
        self._scope: _SessionScope | None = None
        self._scope_token: Token[_SessionScope | None] | None = None

    async def connect(self):
        if self.session is not None:
            raise RuntimeError("This PgConnection is already connected")

        current_task = asyncio.current_task()
        current_scope = _current_session_scope.get()
        if (
            current_scope is not None
            and current_scope.active
            and current_scope.task is current_task
        ):
            # Repository helpers often open their own PgConnection while a webhook
            # already owns one. Reusing it in the same task prevents nested pool
            # checkouts; sessions are never shared with concurrently running tasks.
            self.session = current_scope.session
            self._scope = current_scope
            return

        try:
            self.session = get_session_factory()()
            self._owns_session = True
            self._scope = _SessionScope(self.session, current_task)
            self._scope_token = _current_session_scope.set(self._scope)
        except Exception as error:
            await logger.error("Database", f"Error while creating session: {error}")
            raise

        try:
            await logger.info("Database", "Connection", "New SQLAlchemy Session")
        except asyncio.CancelledError:
            # __aenter__ will not call __aexit__ when cancellation happens here.
            # Close explicitly so the just-created session cannot leak.
            await self.close()
            raise
        except Exception as log_error:
            sys.stderr.write(f"Logging error during database session creation: {log_error}\n")

    async def close(self):
        session = self.session
        if session is None:
            return

        if not self._owns_session:
            self.session = None
            self._scope = None
            return

        async def cleanup() -> None:
            try:
                if session.in_transaction():
                    await session.rollback()
            finally:
                await session.close()

        cleanup_task = asyncio.create_task(cleanup())
        cancellation_requested = False
        cleanup_error: BaseException | None = None

        # A cancelled webhook must not abandon session.close(). Keep the cleanup
        # task strongly referenced and wait until the connection is checked in.
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cancellation_requested = True
            except BaseException as error:
                cleanup_error = error
                break

        if cleanup_error is None and cleanup_task.done() and not cleanup_task.cancelled():
            cleanup_error = cleanup_task.exception()

        try:
            if cleanup_error is not None:
                try:
                    await logger.error(
                        "Database",
                        "SessionCloseError",
                        str(cleanup_error),
                    )
                except Exception:
                    pass
            else:
                try:
                    await logger.info("Database", "Connection", "Session Closed")
                except Exception as log_error:
                    sys.stderr.write(
                        f"Logging error during database session close: {log_error}\n"
                    )
        finally:
            if self._scope is not None:
                self._scope.active = False
            if self._scope_token is not None:
                try:
                    _current_session_scope.reset(self._scope_token)
                except ValueError:
                    # close() may be delegated to another task. The originating
                    # context still sees the scope as inactive and cannot reuse it.
                    _current_session_scope.set(None)
            self.session = None
            self._owns_session = False
            self._scope = None
            self._scope_token = None

        if cancellation_requested:
            raise asyncio.CancelledError

    async def __aenter__(self):
        await self.connect()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def get_db():
    async with PgConnection() as session:
        yield session
