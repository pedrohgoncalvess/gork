from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MessageRepository
from log import logger
from services import save_image_if_new, save_video_if_new, verifiy_media
from utils import INSTANCE_NUMBER


async def process_sent_message(
        body: dict,
        remote_id: str,
        db: AsyncSession,
        is_group: bool
):
    user_repo = UserRepository(db)
    message_repo = MessageRepository(db)
    group_repo = GroupRepository(db)

    event_data = body["data"]
    message_id = event_data["key"]["id"]
    context_message = verifiy_media(body)
    quoted_message_ext_id = context_message.get("quoted_message")
    content = context_message.get("text_message", "")

    quoted_message = (
        await message_repo.find_by_message_id(quoted_message_ext_id)
        if quoted_message_ext_id
        else None
    )

    user_gork = await user_repo.find_by_phone_or_id(INSTANCE_NUMBER)
    if not user_gork:
        await logger.error("Receive message", "Gork user not found.", f"{user_gork}.")
        return

    if is_group:
        group = await group_repo.find_or_create(group_jid=remote_id)
        group_id = group.id
    else:
        group_id = None

    db_message = await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user_gork.id,
        content=content,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"]),
        group_id=group_id,
        quoted_message_id=quoted_message.id if quoted_message else None,
    )

    if context_message.get("image_message"):
        media = await save_image_if_new(
            db=db,
            user_id=user_gork.id,
            message_id=message_id,
            image_message_id=context_message["image_message"],
            group_id=group_id,
        )
        media_id = media.id
    elif context_message.get("video_message") or context_message.get("video_quote"):
        video_id = context_message.get("video_message") or context_message.get("video_quote")
        media = await save_video_if_new(
            db=db,
            user_id=user_gork.id,
            message_id=message_id,
            video_message_id=video_id,
            group_id=group_id,
        )
        media_id = media.id if media else None
    else:
        media_id = None

    if media_id:
        await message_repo.update(db_message.id, {"media_id": media_id})

    return
