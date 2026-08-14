import base64
import hashlib
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.describe_image import describe_image_agent
from database.models.content import Media
from database.operations.content import MediaRepository, MessageRepository
from embeddings import generate_text_embeddings
from external.evolution import download_media
from log import logger
from services.save_media import save_media_if_new
from utils import get_phash


PHASH_MAX_DISTANCE = 8


async def save_image_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        image_message_id: str,
        group_id: Optional[int] = None,
        media_type: str = "image",
) -> Media | None:
    media_base64, name = await download_media(image_message_id)
    if not media_base64:
        return None

    decoded = base64.b64decode(media_base64)
    media_hash = hashlib.sha256(decoded).digest()

    media_repo = MediaRepository(db)
    message_repo = MessageRepository(db)
    message = await message_repo.find_by_message_id(message_id)
    message_id_db = message.id if message else None
    message_media_id = message.media_id if message else None

    existing_media = await media_repo.find_by_hash(media_hash)
    if existing_media:
        if message_id_db and message_media_id != existing_media.id:
            await message_repo.update(message_id_db, {"media_id": existing_media.id})
        return existing_media

    phash = None
    try:
        phash = get_phash(media_base64)
        similar_media = await media_repo.find_by_similar_phash(phash, max_distance=PHASH_MAX_DISTANCE)
        if similar_media:
            if message_id_db and message_media_id != similar_media.id:
                await message_repo.update(message_id_db, {"media_id": similar_media.id})
            return similar_media
    except Exception as e:
        await logger.warning("Media", "PerceptualHash", f"Failed to compute or match phash for {message_id}: {e}")

    description = None
    description_embedding = None

    try:
        target_message = message
        if not target_message:
            target_message = await message_repo.find_by_message_id(message_id)

        if target_message:
            description = await describe_image_agent(
                db=db,
                user_id=user_id,
                db_message=target_message,
                image_base64=media_base64,
            )

            if description:
                description_embedding = await generate_text_embeddings(
                    text=description,
                    message_id=message_id,
                    db=db,
                    user_id=user_id,
                    group_id=group_id,
                )
    except Exception as e:
        await logger.error("Media", "Describe/Embedding", f"Failed to describe/embed image for {message_id}: {e}")

    return await save_media_if_new(
        db=db,
        user_id=user_id,
        message_id=message_id,
        media_message_id=image_message_id,
        media_type=media_type,
        group_id=group_id,
        description=description,
        description_embedding=description_embedding,
        phash=phash,
        media_base64=media_base64,
        media_name=name,
    )

