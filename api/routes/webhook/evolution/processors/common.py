from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles import (
    clean_text, has_explicit_command, handle_help_command,
    handle_conversation_agent, handle_remember_command, handle_sticker_command,
    handle_image_command, handle_transcribe_command, handle_resume_command,
    handle_model_command, handle_consumption_command, handle_describe_image_command,
    handle_list_images_command, handle_favorite_message, handle_list_favorites_message,
    handle_remove_favorite, handle_picture_command, handle_twitter_command,
    handle_instagram_command
)
from database.models.base import User
from database.models.content import Message


async def process_commands(
        conversation: str,
        remote_id: str,
        message_id: str,
        user: User,
        body: dict,
        group_id: Optional[int],
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
        context: dict[str, str],
        db_message: Message,
):
    treated_text = clean_text(conversation)
    has_explicit = has_explicit_command(conversation)

    if has_explicit:
        await process_explicit_commands(
            conversation, remote_id, message_id, user,
            body, group_id, treated_text, db, scheduler, context, db_message
        )
    else:
        pass
        # await process_intent_based_commands(
        #     conversation, remote_id, message_id, user,
        #     body, group_id, treated_text, db, scheduler, context, db_message
        # )


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
        context: dict[str, str],
        db_message: Message,
):
    lw_conversation = conversation.lower()
    if "!help" in lw_conversation:
        await handle_help_command(remote_id, message_id)
        return

    if "!model" in lw_conversation:
        await handle_model_command(remote_id, message_id, db)
        return

    if "!resume" in lw_conversation:
        await handle_resume_command(remote_id, message_id, user.id, group_id)
        return

    if "!transcribe" in lw_conversation:
        await handle_transcribe_command(remote_id, message_id, body, user.id, group_id)
        return

    if "!image" in lw_conversation:
        await handle_image_command(remote_id, user.id, conversation, body, group_id)
        return

    if "!describe" in lw_conversation:
        await handle_describe_image_command(remote_id, user.id, treated_text, context, db, group_id)
        return

    if "!sticker" in lw_conversation:
        await handle_sticker_command(remote_id, body, treated_text, conversation, db, context)
        return

    if "!remember" in lw_conversation:
        await handle_remember_command(
            scheduler, remote_id, message_id, user.id, treated_text, group_id
        )
        return

    if "!consumption" in lw_conversation:
        if group_id:
            await handle_consumption_command(remote_id, group_id=group_id)
        else:
            await handle_consumption_command(remote_id, user_id=user.id)
        return

    if "!gallery" in lw_conversation:
        if group_id:
            await handle_list_images_command(remote_id, treated_text, db, group_id=group_id)
        else:
            await handle_list_images_command(remote_id, treated_text, db, user_id=user.id)
        return

    if "!picture" in lw_conversation:
        await handle_picture_command(remote_id, context, db)
        return

    if "!favorite" in lw_conversation:
        if "!list" in lw_conversation:
            await handle_list_favorites_message(remote_id, db, message_id, user.id, group_id)
            return

        if "!remove" in lw_conversation:
            await handle_remove_favorite(remote_id, db, conversation, user.id if not group_id else None, group_id)
            return

        await handle_favorite_message(remote_id, context, db)
        return

    if "!twitter" in lw_conversation:
        await handle_twitter_command(remote_id, conversation, message_id)
        return

    if "!instagram" in lw_conversation:
        await handle_instagram_command(remote_id, conversation, message_id)
        return

    # Fallback: no known explicit command matched — use conversation agent
    await handle_conversation_agent(
        remote_id=remote_id,
        message_id=message_id,
        user=user,
        db_message=db_message,
        db=db,
        scheduler=scheduler,
        context=context,
        group_id=group_id,
    )
