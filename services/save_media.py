import base64
import hashlib
from datetime import datetime
from pathlib import PurePosixPath
from typing import Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Media
from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MediaRepository, MessageRepository
from external.evolution import download_media
from s3 import S3Client


MEDIA_DEFAULTS = {
    "audio": ("ogg", "audio/ogg"),
    "image": ("jpg", "image/jpeg"),
    "sticker": ("webp", "image/webp"),
    "video": ("mp4", "video/mp4"),
}


def _extension_from_name(name: str | None, media_type: str) -> str:
    default_extension, _ = MEDIA_DEFAULTS.get(media_type, ("bin", "application/octet-stream"))
    if not name:
        return default_extension

    suffix = PurePosixPath(name).suffix.lstrip(".").lower()
    return suffix or default_extension


def _content_type(media_type: str, extension: str) -> str:
    _, default_content_type = MEDIA_DEFAULTS.get(
        media_type, ("bin", "application/octet-stream")
    )
    if media_type == "image" and extension in {"png", "gif", "webp", "jpeg", "jpg"}:
        normalized = "jpeg" if extension == "jpg" else extension
        return f"image/{normalized}"
    return default_content_type


async def save_media_if_new(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        media_message_id: str,
        media_type: str,
        group_id: Optional[int] = None,
        description: Optional[str] = None,
        description_embedding: Optional[list[float]] = None,
        phash: Optional[int] = None,
        media_base64: Optional[str] = None,
        media_name: Optional[str] = None,
) -> Media | None:
    if not media_base64:
        media_base64, name = await download_media(media_message_id)
    else:
        name = media_name

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

    if group_id is not None:
        group_repo = GroupRepository(db)
        group = await group_repo.find_by_id(group_id)
        ext_id = group.ext_id
    else:
        user_repo = UserRepository(db)
        user = await user_repo.find_by_id(user_id)
        ext_id = user.ext_id

    media_id = uuid4()
    extension = _extension_from_name(name, media_type)
    path = f"{ext_id}/{datetime.now().strftime('%Y-%m-%d')}/{media_id}.{extension}"

    s3_conn = S3Client()
    await s3_conn.connect()
    await s3_conn.upload_bytes(
        decoded,
        object_name=path,
        content_type=_content_type(media_type, extension),
    )

    try:
        new_media = await media_repo.insert(
            Media(
                ext_id=media_id,
                name=name or f"{media_type}.{extension}",
                bucket="whatsapp",
                path=path,
                type=media_type,
                description=description,
                description_embedding=description_embedding,
                hash=media_hash,
                phash=phash,
                size=len(decoded) / (1024 * 1024),
            )
        )
    except ValueError as e:
        if "Erro de integridade" in str(e):
            existing_media = await media_repo.find_by_hash(media_hash)
            if existing_media:
                if message_id_db and message_media_id != existing_media.id:
                    await message_repo.update(message_id_db, {"media_id": existing_media.id})
                return existing_media
        raise e

    if message_id_db:
        await message_repo.update(message_id_db, {"media_id": new_media.id})

    return new_media
