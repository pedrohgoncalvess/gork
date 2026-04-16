from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.functions.transcribe_audio import transcribe_audio
from api.routes.webhook.evolution.handles import is_message_too_old
from api.routes.webhook.evolution.processors.common import process_commands
from database.models.base import User, WhiteList
from database.models.content import Message
from database.operations.base import UserRepository, WhiteListRepository
from database.operations.content import MessageRepository
from external.evolution import send_message
from services import verifiy_media, save_profile_pic


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

    user_repo = UserRepository(User, db)
    message_repo = MessageRepository(Message, db)
    whitelist_repo = WhiteListRepository(WhiteList, db)

    user = await user_repo.find_or_create(name=contact_name, lid=remote_id, phone_number=number)
    _ = await save_profile_pic(user.id)

    is_whitelisted = await whitelist_repo.is_whitelisted(
        sender_type="user",
        sender_id=user.id
    )

    conversation = context.get("text_message", "")

    await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=None,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"])
    )

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
        context
    )
