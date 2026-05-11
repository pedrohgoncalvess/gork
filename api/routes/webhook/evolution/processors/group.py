from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.audio import transcribe_audio
from api.routes.webhook.evolution.handles.core import is_message_too_old
from api.routes.webhook.evolution.processors.common import process_commands
from database.operations.base import GroupRepository, UserRepository, WhiteListRepository
from database.operations.content import MessageRepository
from external.evolution import get_group_info, send_message
from log import logger
from services import save_image_if_new, save_profile_pic, save_video_if_new, verifiy_media
from services.message_buffer import buffer_group_message, clear_group_message_buffer
from utils import INSTANCE_NUMBER


async def process_group_message(
        body: dict,
        remote_id: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
):
    group_jid = remote_id.replace("@g.us", "")
    event_data = body["data"]
    contact_id = event_data["key"]["participant"].replace("@lid", "")
    phone_number = event_data["key"].get("participantAlt", "").replace("@s.whatsapp.net", "")
    contact_name = event_data["pushName"]
    message_id = event_data["key"]["id"]
    context_message = verifiy_media(body)

    if await is_message_too_old(event_data["messageTimestamp"]):
        return

    user_repo = UserRepository(db)
    group_repo = GroupRepository(db)
    message_repo = MessageRepository(db)
    whitelist_repo = WhiteListRepository(db)
    user_gork = await user_repo.find_by_phone(INSTANCE_NUMBER)

    user = await user_repo.find_or_create(name=contact_name, lid=contact_id, phone_number=phone_number)
    _ = await save_profile_pic(user.id)

    group = await group_repo.find_or_create(group_jid=group_jid)

    if not group.name:
        gp_infos = get_group_info(remote_id)
        group = await group_repo.find_or_create(
            group_jid=group_jid,
            name=gp_infos["subject"],
            description=gp_infos.get("desc"),
        )

    is_whitelisted = await whitelist_repo.is_whitelisted(
        sender_type="group",
        sender_id=group.id
    )

    conversation = context_message.get("text_message", "")
    quoted_message_ext_id = context_message.get("quoted_message")
    quoted_message = (
        await message_repo.find_by_message_id(quoted_message_ext_id)
        if quoted_message_ext_id
        else None
    )

    db_message = await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=group.id,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"]),
        quoted_message_id=quoted_message.id if quoted_message else None
    )

    if context_message.get("image_message"):
        media_message = await save_image_if_new(
            db=db,
            user_id=user.id,
            message_id=message_id,
            image_message_id=context_message["image_message"],
            group_id=group.id,
        )
        media_id = media_message.id if media_message else None
    elif context_message.get("video_message"):
        video_id = context_message.get("video_message")
        media_message = await save_video_if_new(
            db=db,
            user_id=user.id,
            message_id=message_id,
            video_message_id=video_id,
            group_id=group.id,
        )
        media_id = media_message.id if media_message else None
    else:
        media_id = None

    if media_id:
        db_message = await message_repo.update(db_message.id, {"media_id": media_id})

    if not is_whitelisted:
        return

    mentions: list[str] = context_message.get("mentions", [])

    is_mention = False
    for mention in mentions:
        if not is_mention:
            tt_mention = (mention
                          .replace("@lid", "")
                          .replace("s.whatsapp.net", "")
                          .replace("@", "")
                          ).strip()
            if tt_mention == INSTANCE_NUMBER or (user_gork and tt_mention == user_gork.src_id):
                is_mention = True

    is_reply_to_gork = bool(
        quoted_message
        and user_gork
        and quoted_message.user_id == user_gork.id
    )

    if is_mention or is_reply_to_gork:
        if group.auto_message:
            await clear_group_message_buffer(group.id)

    if not is_mention and not is_reply_to_gork:
        if group.auto_message:
            await buffer_group_message(
                group_id=group.id,
                message_db_id=db_message.id,
                remote_id=remote_id,
                scheduler=scheduler,
            )
        return

    if "audio_message" in context_message.keys():
        conversation = await transcribe_audio(body, user.id, group.id)

    if "!status" in conversation:
        await send_message(remote_id, "🤖 Robo do mito está pronto", message_id)
        return

    await process_commands(
        conversation,
        remote_id,
        message_id,
        user,
        body,
        group.id,
        db,
        scheduler,
        context_message,
        db_message,
    )
