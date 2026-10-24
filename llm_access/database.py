from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.models.content import Media, Message


DEFAULT_LIMIT = 50
MAX_LIMIT = 100
DEFAULT_MESSAGE_LIMIT = 200
MAX_MESSAGE_LIMIT = 2_000


def _limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _message_limit(value: int | None) -> int:
    if value is None:
        return DEFAULT_MESSAGE_LIMIT
    return max(1, min(value, MAX_MESSAGE_LIMIT))


def _like(value: str | None) -> str | None:
    if not value:
        return None
    return f"%{value.strip()}%"


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _matching_messages(db, statement, query, limit):
    if not query or not query.strip():
        return list((await db.execute(statement)).all())
    needle = query.strip().casefold()
    matched, offset = [], 0
    while len(matched) < limit:
        rows = (await db.execute(statement.limit(200).offset(offset))).all()
        matched.extend(row for row in rows if any(
            needle in str(getattr(row, key, '') or '').casefold()
            for key in ('content', 'user_name', 'user_phone_number', 'user_src_id', 'media_type')))
        if len(rows) < 200:
            break
        offset += len(rows)
    return matched[:limit]


async def get_group_users(
        db: AsyncSession,
        group_id: int,
        query: str | None = None,
        limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return users visible to the LLM for a single group.

    The result is intentionally scoped by group_id and only includes users who
    have messages in that group.
    """
    like_query = _like(query)
    stmt = (
        select(
            User.id,
            User.src_id,
            User.phone_number,
            User.name,
            User.profile_pic_path,
        )
        .join(Message, Message.user_id == User.id)
        .where(Message.group_id == group_id)
        .distinct()
        .order_by(User.id)
    )

    result = await db.execute(stmt)
    rows = list(result.all())
    if query and query.strip():
        needle = query.strip().casefold()
        rows = [row for row in rows if any(needle in (getattr(row, key) or '').casefold()
                for key in ('name', 'phone_number', 'src_id'))]
    rows.sort(key=lambda row: ((row.name or '').casefold(), row.id))
    return [
        {
            "id": row.id,
            "src_id": row.src_id,
            "phone_number": row.phone_number,
            "name": row.name,
            "profile_pic_path": row.profile_pic_path,
        }
        for row in rows[:_limit(limit)]
    ]


async def get_group_messages(
        db: AsyncSession,
        group_id: int,
        query: str | None = None,
        limit: int | None = None,
        user_id: int | None = None,
        media_type: str | None = None,
        include_deleted: bool = False,
) -> list[dict[str, Any]]:
    """
    Return messages visible to the LLM for a single group.

    Media data is deliberately reduced to the media type so the model can know
    what kind of attachment exists without receiving storage paths or content.
    """
    filters = [Message.group_id == group_id]
    if not include_deleted:
        filters.append(Message.deleted_at.is_(None))
    if user_id:
        filters.append(Message.user_id == user_id)
    if media_type:
        filters.append(Media.type == media_type)

    stmt = (
        select(
            Message.id,
            Message.message_id,
            Message.content,
            Message.created_at,
            Message.quoted_message_id,
            Message.is_favorite,
            User.id.label("user_id"),
            User.src_id.label("user_src_id"),
            User.phone_number.label("user_phone_number"),
            User.name.label("user_name"),
            Media.type.label("media_type"),
        )
        .join(User, Message.user_id == User.id)
        .outerjoin(Media, Message.media_id == Media.id)
        .where(and_(*filters))
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(_message_limit(limit))
    )

    rows = await _matching_messages(db, stmt, query, _message_limit(limit))
    return [
        {
            "id": row.id,
            "message_id": row.message_id,
            "content": row.content,
            "created_at": _serialize_datetime(row.created_at),
            "quoted_message_id": row.quoted_message_id,
            "is_favorite": row.is_favorite,
            "sender": {
                "id": row.user_id,
                "src_id": row.user_src_id,
                "phone_number": row.user_phone_number,
                "name": row.user_name,
            },
            "media_type": row.media_type,
        }
        for row in reversed(rows)
    ]


async def get_user_messages(
        db: AsyncSession,
        group_id: int,
        user_id: int,
        query: str | None = None,
        limit: int | None = None,
        include_deleted: bool = False,
) -> list[dict[str, Any]]:
    return await get_group_messages(
        db=db,
        group_id=group_id,
        user_id=user_id,
        query=query,
        limit=limit,
        include_deleted=include_deleted,
    )


async def get_conversation_messages(
        db: AsyncSession,
        user_id: int,
        gork_user_id: int,
        query: str | None = None,
        limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return history from one private conversation, never from groups."""
    filters = [
        Message.group_id.is_(None),
        Message.user_id.in_([user_id, gork_user_id]),
        Message.deleted_at.is_(None),
    ]

    stmt = (
        select(
            Message.id,
            Message.message_id,
            Message.content,
            Message.created_at,
            Message.quoted_message_id,
            Message.is_favorite,
            User.id.label("user_id"),
            User.src_id.label("user_src_id"),
            User.phone_number.label("user_phone_number"),
            User.name.label("user_name"),
            Media.type.label("media_type"),
        )
        .join(User, Message.user_id == User.id)
        .outerjoin(Media, Message.media_id == Media.id)
        .where(and_(*filters))
        .order_by(desc(Message.created_at), desc(Message.id))
        .limit(_message_limit(limit))
    )

    rows = await _matching_messages(db, stmt, query, _message_limit(limit))
    return [
        {
            "id": row.id,
            "message_id": row.message_id,
            "content": row.content,
            "created_at": _serialize_datetime(row.created_at),
            "quoted_message_id": row.quoted_message_id,
            "is_favorite": row.is_favorite,
            "sender": {
                "id": row.user_id,
                "src_id": row.user_src_id,
                "phone_number": row.user_phone_number,
                "name": row.user_name,
            },
            "media_type": row.media_type,
        }
        for row in reversed(rows)
    ]


async def search_messages(
        db: AsyncSession,
        group_id: int,
        query: str,
        limit: int | None = None,
        user_id: int | None = None,
        media_type: str | None = None,
        include_deleted: bool = False,
) -> list[dict[str, Any]]:
    return await get_group_messages(
        db=db,
        group_id=group_id,
        query=query,
        limit=limit,
        user_id=user_id,
        media_type=media_type,
        include_deleted=include_deleted,
    )


async def get_user_images(
        db: AsyncSession,
        group_id: int,
        user_id: int,
        limit: int | None = None,
) -> list[dict[str, Any]]:
    return await get_group_messages(
        db=db,
        group_id=group_id,
        user_id=user_id,
        media_type="image",
        limit=limit,
    )
