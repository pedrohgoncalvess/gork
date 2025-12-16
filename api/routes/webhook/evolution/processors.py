from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles import (
    clean_text, has_explicit_command, handle_help_command,
    handle_generic_conversation, handle_remember_command, handle_sticker_command,
    handle_image_command, handle_search_command, handle_transcribe_command,
    handle_resume_command, handle_model_command, COMMANDS,
    is_message_too_old, extract_conversation_text,
    handle_consumption_command, handle_describe_image_command, handle_list_images_command
)
from database.models.base import User, Group, WhiteList
from database.models.content import Message
from database.operations.base import UserRepository, GroupRepository, WhiteListRepository
from database.operations.content import MessageRepository
from external import get_group_info
from external.evolution import send_message
from functions import transcribe_audio, classify_intent
from services import verifiy_media, save_profile_pic
from utils import get_env_var


async def process_group_message(
        body: dict,
        event_data: dict,
        message_data: dict,
        remote_id: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
):
    group_jid = remote_id.replace("@g.us", "")
    contact_id = event_data["key"]["participant"].replace("@lid", "")
    phone_number = event_data["key"].get("participantAlt", "").replace("@s.whatsapp.net", "")
    contact_name = event_data["pushName"]
    message_id = event_data["key"]["id"]
    instance_number = get_env_var("EVOLUTION_INSTANCE_NUMBER")

    if await is_message_too_old(event_data["messageTimestamp"]):
        return

    user_repo = UserRepository(User, db)
    group_repo = GroupRepository(Group, db)
    message_repo = MessageRepository(Message, db)
    whitelist_repo = WhiteListRepository(WhiteList, db)
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

    conversation = await extract_conversation_text(message_data)

    await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=group.id,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"])
    )

    if not is_whitelisted:
        return

    mentions: list[str] = event_data.get("contextInfo", {}).get("mentionedJid", [])
    if not mentions:
        mentions = (
            message_data.get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo", {})
            .get("mentionedJid", [])
        )

    is_mention = False
    for mention in mentions:
        if not is_mention:
            tt_mention = (mention
                          .replace("@lid", "")
                          .replace("s.whatsapp.net", "")
                          .replace("@", "")
                          ).strip()
            if tt_mention == instance_number or tt_mention == user_gork.src_id:
                is_mention = True

    if not is_mention:
        return

    medias = verifiy_media(body)
    if "audio_message" in medias.keys():
        conversation = await transcribe_audio(body, user.id, group.id)

    if conversation in [f"@{instance_number}", f"@{user_gork.src_id}"]:
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
        medias
    )


async def process_private_message(
        body: dict,
        event_data: dict,
        message_data: dict,
        remote_id: str,
        number: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler
):
    contact_name = event_data["pushName"]
    message_id = event_data["key"]["id"]

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

    conversation = await extract_conversation_text(message_data)

    await message_repo.find_or_create(
        message_id=message_id,
        sender_id=user.id,
        group_id=None,
        content=conversation,
        created_at=datetime.fromtimestamp(event_data["messageTimestamp"])
    )

    if not is_whitelisted:
        await send_message(
            remote_id,
            "⚠️ Você não tem permissão para usar este bot. Entre em contato com o administrador.",
            message_id
        )
        return

    medias = verifiy_media(body)
    if "audio_message" in medias.keys():
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
        medias
    )


async def process_explicit_commands(
        conversation: str,
        remote_id: str,
        message_id: str,
        user: User,
        body: dict,
        group_id: Optional[int],
        treated_text: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
        context: dict[str, str]
):
    if "!help" in conversation.lower():
        await handle_help_command(remote_id, message_id)
        return

    if "!model" in conversation.lower():
        await handle_model_command(remote_id, message_id, db)
        return

    if "!resume" in conversation.lower():
        await handle_resume_command(remote_id, message_id, user.id, group_id)
        return

    if "!transcribe" in conversation.lower():
        await handle_transcribe_command(remote_id, message_id, body, user.id, group_id)
        return

    if "!search" in conversation.lower():
        group = True if group_id else False
        await handle_search_command(remote_id, message_id, treated_text, group, user.id)
        return

    if "!image" in conversation.lower():
        await handle_image_command(remote_id, user.id, treated_text, body, group_id)
        return

    if "!describe" in conversation.lower():
        await handle_describe_image_command(remote_id, user.id, treated_text, body, group_id)
        return

    if "!sticker" in conversation.lower():
        await handle_sticker_command(remote_id, body, treated_text, conversation, db)
        return

    if "!remember" in conversation.lower():
        await handle_remember_command(
            scheduler, remote_id, message_id, user.id, treated_text, group_id
        )
        return

    if "!consumption" in conversation.lower():
        if group_id:
            await handle_consumption_command(
                remote_id, group_id=group_id
            )
        else:
            await handle_consumption_command(
                remote_id, user_id=user.id
            )
        return

    if "!gallery" in conversation.lower():
        if group_id:
            await handle_list_images_command(
                remote_id, treated_text,
                db, group_id=group_id
            )
        else:
            await handle_list_images_command(
                remote_id, treated_text,
                db, user_id=user.id
            )
        return

    await handle_generic_conversation(
        remote_id, message_id, user, treated_text, context, group_id
    )


async def process_commands(
        conversation: str,
        remote_id: str,
        message_id: str,
        user: User,
        body: dict,
        group_id: Optional[int],
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
        medias: dict[str, str]
):
    treated_text = clean_text(conversation)

    has_explicit = has_explicit_command(conversation)

    if has_explicit:
        await process_explicit_commands(
            conversation, remote_id, message_id, user,
            body, group_id, treated_text, db, scheduler, medias
        )
    else:
        await process_intent_based_commands(
            conversation, remote_id, message_id, user,
            body, group_id, treated_text, db, scheduler, medias
        )


async def process_intent_based_commands(
        conversation: str,
        remote_id: str,
        message_id: str,
        user: User,
        body: dict,
        group_id: Optional[int],
        treated_text: str,
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
        medias: dict[str, str]
):
    intent, wants_audio = await classify_intent(conversation, db, COMMANDS, medias, user.id, group_id)
    is_group = True if group_id else False

    intent_handlers = {
        "help": lambda: handle_help_command(remote_id, message_id),
        "model": lambda: handle_model_command(remote_id, message_id, db),
        "resume": lambda: handle_resume_command(remote_id, message_id, user.id, group_id),
        "transcribe": lambda: handle_transcribe_command(remote_id, message_id, body, user.id, group_id),
        "search": lambda: handle_search_command(remote_id, message_id, treated_text, is_group, user.id),
        "image": lambda: handle_image_command(remote_id, user.id, treated_text, body, group_id),
        "sticker": lambda: handle_sticker_command(remote_id, body, treated_text, conversation, db),
        "remember": lambda: handle_remember_command(scheduler, remote_id, message_id, user.id, treated_text, group_id),
    }

    handler = intent_handlers.get(intent)

    if handler:
        await handler()
    else:
        await handle_generic_conversation(
            remote_id, message_id, user, treated_text, medias, group_id, wants_audio
        )