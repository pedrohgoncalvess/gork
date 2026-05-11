import base64
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Media
from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MediaRepository, MessageRepository
from external.evolution import download_media
from s3 import S3Client
from utils import get_image_hash


async def save_video_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        video_message_id: str,
        group_id: Optional[int] = None,
) -> Media | None:

    video_base64, name = await download_media(video_message_id)

    decoded = base64.b64decode(video_base64)
    video_hash = get_image_hash(video_base64)

    media_repo = MediaRepository(db)
    message_repo = MessageRepository(db)
    message = await message_repo.find_by_message_id(message_id)

    existing_media = await media_repo.find_by_hash(video_hash)
    if existing_media:
        if message and message.media_id != existing_media.id:
            await message_repo.update(message.id, {"media_id": existing_media.id})
        return existing_media

    if group_id is not None:
        group_repo = GroupRepository(db)
        group = await group_repo.find_by_id(group_id)
        ext_id = group.ext_id
    else:
        user_repo = UserRepository(db)
        user = await user_repo.find_by_id(user_id)
        ext_id = user.ext_id

    s3_conn = S3Client()
    _ = await s3_conn.connect()
    video_id = uuid4()
    path = f"{ext_id}/{datetime.now().strftime('%Y-%m-%d')}/{video_id}.mp4"
    _ = await s3_conn.upload_video(
        decoded,
        object_name=path
    )

    new_media = await media_repo.insert(
        Media(
            ext_id=video_id,
            name=name,
            bucket="whatsapp",
            path=path,
            type="video",
            description=None,
            description_embedding=None,
            hash=video_hash,
            phash=None,
            size=len(decoded) / (1024 * 1024),
        )
    )

    if message:
        await message_repo.update(message.id, {"media_id": new_media.id})

    return new_media
