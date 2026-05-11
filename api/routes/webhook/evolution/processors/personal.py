from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.audio import transcribe_audio
from api.routes.webhook.evolution.handles.core import is_message_too_old
from api.routes.webhook.evolution.processors.common import process_commands
from database.operations.base import UserRepository, WhiteListRepository
from database.operations.content import MessageRepository
from external.evolution import send_message
from services import save_image_if_new, save_profile_pic, save_video_if_new, verifiy_media


async def process_private_message(
        body: dict,
        event_data: dict,
        remote_id: str,
        number: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler
):
    contact_name = event_data["pushName"]
    message_id = event_data["key"]["id"]
    context = verifiy_media(body)

    if await is_message_too_old(event_data["messageTimestamp"]):
        return

    user_repo = UserRepository(db)
    message_repo = MessageRepository(db)
    whitelist_repo = WhiteListRepository(db)

    user = await user_repo.find_or_create(name=contact_name, lid=remote_id, phone_number=number)
    _ = await save_profile_pic(user.id)

    is_whitelisted = await whitelist_repo.is_whitelisted(
        sender_type="user",
        sender_id=user.id
    )

    conversation = context.get("text_message", "")

    db_message = await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=None,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"]),
    )

    if context.get("image_message"):
        media = await save_image_if_new(
            db=db,
            user_id=user.id,
            message_id=message_id,
            image_message_id=context["image_message"],
            group_id=None,
        )
        media_id = media.id if media else None
    elif context.get("video_message") or context.get("video_quote"):
        video_id = context.get("video_message") or context.get("video_quote")
        media = await save_video_if_new(
            db=db,
            user_id=user.id,
            message_id=message_id,
            video_message_id=video_id,
            group_id=None,
        )
        media_id = media.id if media else None
    else:
        media_id = None

    if media_id:
        db_message = await message_repo.update(db_message.id, {"media_id": media_id})

    if not is_whitelisted:
        return

    if "audio_message" in context.keys():
        conversation = await transcribe_audio(body, user.id, group_id=None)

    if "!status" in conversation:
        await send_message(number, "🤖 Robo do mito está pronto", message_id)
        return

    await process_commands(
        conversation,
        number,
        message_id,
        user,
        body,
        None,
        db,
        scheduler,
        context,
        db_message,
    )
