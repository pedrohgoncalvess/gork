from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Media
from services.save_media import save_media_if_new


async def save_video_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        video_message_id: str,
        group_id: Optional[int] = None,
) -> Media | None:
    return await save_media_if_new(
        db=db,
        user_id=user_id,
        message_id=message_id,
        media_message_id=video_message_id,
        media_type="video",
        group_id=group_id,
    )
