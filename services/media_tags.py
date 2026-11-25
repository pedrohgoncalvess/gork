from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from sqlalchemy import text

from database.connection import get_session_factory


class MediaTagBusy(RuntimeError):
    pass


async def mark_media(user_id: int, kind: str, source_id: str, command_id: str,
                     marked_at: datetime) -> None:
    async with get_session_factory().begin() as db:
        await db.execute(text("""
            INSERT INTO content.media_tag
                (user_id, kind, source_message_id, command_message_id, marked_at)
            VALUES (:user, :kind, :source, :command, :marked_at)
            ON CONFLICT (command_message_id) DO NOTHING
        """), {"user": user_id, "kind": kind, "source": source_id,
               "command": command_id, "marked_at": marked_at})


@asynccontextmanager
async def pending_media_tag(user_id: int, kind: str):
    """Consume the latest tag only after a successful send."""
    claim = uuid4()
    async with get_session_factory().begin() as db:
        result = await db.execute(text("""
            WITH latest AS (
                SELECT id, consumed_at FROM content.media_tag
                WHERE user_id = :user AND kind = :kind
                ORDER BY marked_at DESC, id DESC LIMIT 1
            ), claimed AS (
                UPDATE content.media_tag AS tag
                SET claim_id = :claim, claim_until = NOW() + INTERVAL '5 minutes'
                FROM latest
                WHERE tag.id = latest.id AND tag.consumed_at IS NULL
                  AND (tag.claim_until IS NULL OR tag.claim_until <= NOW())
                RETURNING tag.source_message_id
            )
            SELECT latest.id, latest.consumed_at, claimed.source_message_id
            FROM latest LEFT JOIN claimed ON TRUE
        """), {"user": user_id, "kind": kind, "claim": claim})
        tag = result.mappings().first()

    if not tag or tag["consumed_at"] is not None:
        yield None
        return
    if not tag["source_message_id"]:
        raise MediaTagBusy("Seu áudio marcado já está sendo usado em outra figurinha.")

    consumed = False
    try:
        yield tag["source_message_id"]
        consumed = True
    finally:
        async with get_session_factory().begin() as db:
            await db.execute(text("""
                UPDATE content.media_tag
                SET consumed_at = CASE WHEN :consumed THEN NOW() ELSE consumed_at END,
                    claim_id = NULL, claim_until = NULL
                WHERE id = :id AND claim_id = :claim
            """), {"id": tag["id"], "claim": claim, "consumed": consumed})
