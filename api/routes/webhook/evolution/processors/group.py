from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles import transcribe_audio
from api.routes.webhook.evolution.handles import is_message_too_old
from api.routes.webhook.evolution.processors.common import process_commands
from database.operations.base import UserRepository, GroupRepository, WhiteListRepository
from database.operations.content import MessageRepository
from external.evolution import send_message, get_group_info
from services import verifiy_media, save_profile_pic, save_image_if_new
from utils import get_env_var


INSTANCE_NUMBER = get_env_var("EVOLUTION_INSTANCE_NUMBER")

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
    user_gork = await user_repo.find_by_name("Gork")

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

    db_message = await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=group.id,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"])
    )

    if context_message.get("image_message"):
        await save_image_if_new(
            db=db,
            user_id=user.id,
            message_id=message_id,
            image_message_id=context_message["image_message"],
            group_id=group.id,
        )

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
            if tt_mention == INSTANCE_NUMBER or tt_mention == user_gork.src_id:
                is_mention = True

    if not is_mention:
        return

    if "audio_message" in context_message.keys():
        conversation = await transcribe_audio(body, user.id, group.id)

    if conversation in [f"@{INSTANCE_NUMBER}", f"@{user_gork.src_id}"]:
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
