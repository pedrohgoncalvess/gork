from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Media
from services.save_media import save_media_if_new


async def save_image_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        image_message_id: str,
        group_id: Optional[int] = None,
        media_type: str = "image",
) -> Media | None:
    return await save_media_if_new(
        db=db,
        user_id=user_id,
        message_id=message_id,
        media_message_id=image_message_id,
        media_type=media_type,
        group_id=group_id,
    )
