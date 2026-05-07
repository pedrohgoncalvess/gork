import base64
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.describe_image import describe_image_agent
from database import PgConnection
from database.models.content import Media
from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MediaRepository, MessageRepository
from embeddings import generate_text_embeddings
from external.evolution import download_media
from s3 import S3Client
from services.message_context import verifiy_media
from utils import get_image_hash, get_phash


PHASH_MAX_DISTANCE = 8
MEDIA_EMBEDDING_DIMENSION = 2560

def _fit_media_embedding(embedding: list[float]) -> list[float]:
    if len(embedding) == MEDIA_EMBEDDING_DIMENSION:
        return embedding
    if len(embedding) > MEDIA_EMBEDDING_DIMENSION:
        return embedding[:MEDIA_EMBEDDING_DIMENSION]
    return embedding + [0.0] * (MEDIA_EMBEDDING_DIMENSION - len(embedding))


async def save_image_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        image_message_id: str,
        group_id: Optional[int] = None,
        media_type: str = "image",
) -> Media | None:

    image_base64, name = await download_media(image_message_id)

    decoded = base64.b64decode(image_base64)
    image_hash = get_image_hash(image_base64)
    media_repo = MediaRepository(db)
    message_repo = MessageRepository(db)
    message = await message_repo.find_by_message_id(message_id)

    existing_media = await media_repo.find_by_hash(image_hash)
    if existing_media:
        if message and message.media_id != existing_media.id:
            await message_repo.update(message.id, {"media_id": existing_media.id})
        return existing_media

    phash = get_phash(image_base64)
    similar_media = await media_repo.find_by_similar_phash(phash, PHASH_MAX_DISTANCE)
    if similar_media:
        if message and message.media_id != similar_media.id:
            await message_repo.update(message.id, {"media_id": similar_media.id})
        return similar_media

    if group_id is not None:
        group_repo = GroupRepository(db)
        group = await group_repo.find_by_id(group_id)
        ext_id = group.ext_id
    else:
        user_repo = UserRepository(db)
        user = await user_repo.find_by_id(user_id)
        ext_id = user.ext_id

    description = await describe_image_agent(db, user_id, image_message_id, image_base64, group_id)

    text_emb = _fit_media_embedding(
        await generate_text_embeddings(description, message_id, db)
    )

    s3_conn = S3Client()
    _ = await s3_conn.connect()
    image_id = uuid4()
    path = f"{ext_id}/{datetime.now().strftime('%Y-%m-%d')}/{image_id}.png"
    _ = await s3_conn.upload_image(
        decoded,
        object_name=path
    )

    new_media = await media_repo.insert(
        Media(
            ext_id=image_id,
            name=name,
            bucket="whatsapp",
            path=path,
            type=media_type,
            description_embedding=text_emb,
            description=description,
            hash=image_hash,
            phash=phash,
            size=len(decoded) / (1024 * 1024),
        )
    )

    if message:
        await message_repo.update(message.id, {"media_id": new_media.id})

    return new_media
