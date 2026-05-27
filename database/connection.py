"""
Async SQLAlchemy Database Connection Wrapper

Provides an async SQLAlchemy session manager using context manager semantics.
Automatically loads PostgreSQL credentials from environment variables and
initializes an async engine with SQLAlchemy 2.0 style.
"""
import asyncio
import sys

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
        _engine = create_async_engine(
            _database_url(),
            echo=False,
            pool_size=10,
            max_overflow=20,
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

    async def connect(self):
        try:
            self.session = get_session_factory()()
        except Exception as error:
            await logger.error("Database", f"Error while creating session: {error}")
            raise

        try:
            await logger.info("Database", "Connection", "New SQLAlchemy Session")
        except Exception as log_error:
            import sys
            sys.stderr.write(f"Logging error during database session creation: {log_error}\n")

    async def close(self):
        if self.session:
            try:
                await logger.info("Database", "Connection", "Session Closed")
            except Exception as log_error:
                import sys
                sys.stderr.write(f"Logging error during database session close: {log_error}\n")
            
            try:
                await asyncio.shield(self.session.close())
            except Exception as error:
                try:
                    await logger.error("Database", f"Error during session close: {error}")
                except Exception:
                    pass
            finally:
                self.session = None

    async def __aenter__(self):
        await self.connect()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type and self.session:
                await asyncio.shield(self.session.rollback())
        except Exception as error:
            try:
                await logger.error("Database", f"Error during rollback: {error}")
            except Exception:
                pass
        finally:
            await self.close()


async def get_db():
    async with PgConnection() as session:
        yield session
