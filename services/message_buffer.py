import asyncio
import time
import traceback

import redis.asyncio as redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from agents.execution.filter import filter_agent
from api.routes.webhook.evolution.handles.chat import handle_conversation_agent
from database import PgConnection
from database.operations.content import MessageRepository
from log import logger
from utils import get_env_var


BUFFER_LIMIT = 20
BUFFER_GAP_SECONDS = 20
_REDIS_CLIENT: redis.Redis | None = None


def _redis_url() -> str:
    return get_env_var("REDIS_URL") or "redis://localhost:6379/0"


def _client() -> redis.Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = redis.from_url(_redis_url(), decode_responses=True)
    return _REDIS_CLIENT


def _messages_key(group_id: int) -> str:
    return f"group:{group_id}:auto-message:buffer"


def _deadline_key(group_id: int) -> str:
    return f"group:{group_id}:auto-message:deadline"


def _lock_key(group_id: int) -> str:
    return f"group:{group_id}:auto-message:flush-lock"


def _handle_task_exception(task: asyncio.Task) -> None:
    """Callback para capturar exceções de tasks fire-and-forget."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        asyncio.create_task(
            logger.error("GroupMessageBuffer", "TaskError", f"{task.get_name()}: {exc}\n{tb}")
        )


async def clear_group_message_buffer(group_id: int) -> None:
    try:
        client = _client()
        await client.delete(_messages_key(group_id), _deadline_key(group_id))
    except Exception as error:
        await logger.error("GroupMessageBuffer", "ClearError", str(error))


async def buffer_group_message(
        group_id: int,
        message_db_id: int,
        remote_id: str,
        scheduler: AsyncIOScheduler,
) -> None:
    try:
        client = _client()
        messages_key = _messages_key(group_id)
        stored_deadline = await client.get(_deadline_key(group_id))
        if stored_deadline and time.time() >= float(stored_deadline):
            await flush_group_message_buffer(group_id, remote_id, scheduler)

        deadline = time.time() + BUFFER_GAP_SECONDS

        async with client.pipeline(transaction=True) as pipe:
            pipe.rpush(messages_key, message_db_id)
            pipe.expire(messages_key, 60 * 60)
            pipe.set(_deadline_key(group_id), deadline, ex=60 * 60)
            pipe.llen(messages_key)
            results = await pipe.execute()

        buffer_size = int(results[-1])
        if buffer_size >= BUFFER_LIMIT:
            await flush_group_message_buffer(group_id, remote_id, scheduler)
            return

        task = asyncio.create_task(
            _flush_after_gap(group_id, remote_id, scheduler, deadline),
            name=f"flush_after_gap:{group_id}",
        )
        task.add_done_callback(_handle_task_exception)
    except Exception as error:
        await logger.error("GroupMessageBuffer", "BufferError", str(error))


async def _flush_after_gap(
        group_id: int,
        remote_id: str,
        scheduler: AsyncIOScheduler,
        expected_deadline: float,
) -> None:
    try:
        await asyncio.sleep(BUFFER_GAP_SECONDS)
        client = _client()
        stored_deadline = await client.get(_deadline_key(group_id))
        if not stored_deadline:
            return

        if float(stored_deadline) > expected_deadline:
            return

        if time.time() < float(stored_deadline):
            return

        await flush_group_message_buffer(group_id, remote_id, scheduler)
    except Exception as error:
        await logger.error("GroupMessageBuffer", "GapFlushError", str(error))


async def flush_group_message_buffer(
        group_id: int,
        remote_id: str,
        scheduler: AsyncIOScheduler,
) -> None:
    client = None
    lock_key = _lock_key(group_id)

    try:
        client = _client()
        lock_acquired = await client.set(lock_key, "1", nx=True, ex=30)
        if not lock_acquired:
            return

        message_ids = await client.lrange(_messages_key(group_id), 0, -1)
        if not message_ids:
            await client.delete(_deadline_key(group_id))
            return

        async with PgConnection() as db:
            message_repo = MessageRepository(db)
            messages = await message_repo.find_by_ids([int(message_id) for message_id in message_ids])

            if not messages:
                await clear_group_message_buffer(group_id)
                return

            response = await filter_agent(db, messages)
            if not response.get("should_respond"):
                await clear_group_message_buffer(group_id)
                return

            last_message = messages[-1]
            await handle_conversation_agent(
                remote_id=remote_id,
                user=last_message.sender,
                db_message=last_message,
                db=db,
                scheduler=scheduler,
                context={},
            )

        # Limpa o buffer somente após processamento bem-sucedido
        await clear_group_message_buffer(group_id)
    except Exception as error:
        await logger.error("GroupMessageBuffer", "FlushError", str(error))
    finally:
        if client:
            try:
                await client.delete(lock_key)
            except Exception as unlock_error:
                await logger.error("GroupMessageBuffer", "UnlockError", str(unlock_error))
