from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.exceptions import LockError

from log import logger
from utils import get_env_var


_REDIS_CLIENT: redis.Redis | None = None


def _client() -> redis.Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        redis_url = get_env_var("REDIS_URL") or "redis://localhost:6379/0"
        _REDIS_CLIENT = redis.from_url(redis_url, decode_responses=True)
    return _REDIS_CLIENT


@asynccontextmanager
async def _serialize_conversation(lock_key: str, label: str):
    lock = _client().lock(
        lock_key,
        timeout=10 * 60,
        blocking_timeout=3 * 60,
        sleep=0.1,
    )
    acquired = await lock.acquire()
    if not acquired:
        raise TimeoutError(f"Timed out waiting for conversation lock: {label}")

    try:
        yield
    finally:
        try:
            await lock.release()
        except LockError as error:
            await logger.error("ConversationLock", "ReleaseError", f"{label}: {error}")


@asynccontextmanager
async def serialize_direct_message(contact_id: str):
    """Prevent concurrent DM processing across all Gunicorn workers."""
    async with _serialize_conversation(
        f"dm:{contact_id}:conversation-lock",
        f"dm:{contact_id}",
    ):
        yield


@asynccontextmanager
async def serialize_group_conversation(group_id: int):
    """Serialize bot responses for one group across all workers."""
    async with _serialize_conversation(
        f"group:{group_id}:conversation-lock",
        f"group:{group_id}",
    ):
        yield
