"""
Async SQLAlchemy Database Connection Wrapper

Provides an async SQLAlchemy session manager using context manager semantics.
Automatically loads PostgreSQL credentials from environment variables and
initializes an async engine with SQLAlchemy 2.0 style.
"""
import asyncio
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine

from log import logger
from utils import get_env_var


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class PgConnection:
    def __init__(self):
        user = get_env_var("PG_USER")
        password = get_env_var("PG_PASSWORD")
        host = get_env_var("PG_HOST")
        port = get_env_var("PG_PORT")
        db = get_env_var("PG_NAME")

        self.database_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"

        self.engine = create_async_engine(
            self.database_url,
            echo=False,
            pool_size=10,
            max_overflow=20,
            future=True
        )

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

        self.session: AsyncSession | None = None

    async def connect(self):
        try:
            self.session = self.session_factory()
            await logger.info("Database", "Connection", f"New SQLAlchemy Session")
        except Exception as error:
            await logger.error("Database", f"Error while creating session: {error}")
            raise

    async def close(self):
        if self.session:
            await logger.info("Database", "Connection", "Session Closed")
            await self.session.close()

        await self.engine.dispose()

    async def __aenter__(self):
        await self.connect()
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def get_db():
    async with PgConnection() as session:
        yield session
