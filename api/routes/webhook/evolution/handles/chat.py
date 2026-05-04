from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.conversation import conversation_agent
from agents.parser.conversation import parse_gork_response
from database.models.base import User
from database.models.content import Message
from database.operations.content import MessageRepository
from external.evolution import send_message, send_audio
from log import logger
from tts import text_to_speech


async def handle_conversation_agent(
        remote_id: str,
        message_id: str,
        user: User,
        db_message: Message,
        db: AsyncSession,
        scheduler: AsyncIOScheduler,
        context: dict,
        group_id: Optional[int] = None,
):
    """
    Main handle for the conversation agent (refactored from generic_conversation).

    Calls conversation_agent to get a structured JSON response from the LLM,
    then dispatches each action to the appropriate existing handle/service.
    """
    raw_response = await conversation_agent(
        db=db,
        user_id=user.id,
        last_message_id=db_message.id,
        group_id=group_id,
    )

    try:
        parsed = await parse_gork_response(raw_response)
    except ValueError as e:
        await logger.error("ConversationHandle", "ParseError", str(e))
        await send_message(remote_id, "Desculpa, tive um problema interno. Tenta de novo?", message_id)
        return

    actions = parsed.get("actions", [])

    for action in actions:
        action_type = action.get("action")

        try:
            await _dispatch_action(
                action_type=action_type,
                action=action,
                remote_id=remote_id,
                message_id=message_id,
                user=user,
                db=db,
                db_message=db_message,
                scheduler=scheduler,
                context=context,
                group_id=group_id,
            )
        except Exception as e:
            await logger.error("ConversationHandle", f"ActionError:{action_type}", str(e))


async def _dispatch_action(
        action_type: str,
        action: dict,
        remote_id: str,
        message_id: str,
        user: User,
        db: AsyncSession,
        db_message: Message,
        scheduler: AsyncIOScheduler,
        context: dict,
        group_id: Optional[int],
):
    params = action.get("parameters", {}) or {}

    # ── message ──────────────────────────────────────────────────────────────
    if action_type == "message":
        await send_message(remote_id, action.get("content", ""), message_id)

    # ── audio ─────────────────────────────────────────────────────────────────
    elif action_type == "audio":
        text = params.get("text", "")
        language = params.get("language", "pt")
        audio_b64 = await text_to_speech(text, language=language)
        await send_audio(remote_id, audio_b64, message_id)

    # ── sticker ───────────────────────────────────────────────────────────────
    elif action_type == "sticker":
        from api.routes.webhook.evolution.handles.image import handle_sticker_command
        # Build a synthetic context that includes the quoted message_id if provided
        sticker_context = dict(context)
        quoted_id = params.get("message_id")
        if quoted_id:
            sticker_context["image_quote"] = str(quoted_id)

        caption_text = params.get("text", "")
        if params.get("no_background"):
            caption_text = f"{caption_text} :no-background"
        if params.get("effect"):
            caption_text = f"{caption_text} :effect={params['effect']}"
        if params.get("random"):
            caption_text = f"{caption_text} :random"

        await handle_sticker_command(
            remote_id=remote_id,
            body={"sticker_params": params},
            treated_text=caption_text,
            message=action_type,
            db=db,
            message_context=sticker_context,
        )

    # ── picture ───────────────────────────────────────────────────────────────
    elif action_type == "picture":
        from api.routes.webhook.evolution.handles.image import handle_picture_command
        from database.operations.base import UserRepository

        users_requested = params.get("users", [])
        user_repo = UserRepository(db)

        picture_context = dict(context)
        resolved_mentions = []
        for name in users_requested:
            found = await user_repo.find_by_name(name)
            if found:
                resolved_mentions.append(found.src_id or found.phone_number)

        picture_context["mentions"] = resolved_mentions
        picture_context["quoted_message"] = message_id

        await handle_picture_command(remote_id=remote_id, context=picture_context, db=db)

    # ── image ─────────────────────────────────────────────────────────────────
    elif action_type == "image":
        from api.routes.webhook.evolution.handles.image import handle_image_command
        prompt = params.get("prompt", "")
        await handle_image_command(
            remote_id=remote_id,
            user_id=user.id,
            raw_text=prompt,
            body={"data": {"key": {"id": message_id}, "message": {}, "contextInfo": None}},
            group_id=group_id,
        )

    # ── describe ──────────────────────────────────────────────────────────────
    elif action_type == "describe":
        from api.routes.webhook.evolution.handles.image import handle_describe_image_command
        quoted_msg_id = params.get("message_id")
        describe_context = dict(context)
        if quoted_msg_id:
            describe_context["image_quote"] = str(quoted_msg_id)
        await handle_describe_image_command(
            remote_id=remote_id,
            user_id=user.id,
            treated_text="",
            medias=describe_context,
            group_id=group_id,
        )

    # ── search ────────────────────────────────────────────────────────────────
    elif action_type == "search":
        from api.routes.webhook.evolution.handles.search import handle_search_command
        query = params.get("query", "")
        is_group = group_id is not None
        await handle_search_command(remote_id, message_id, query, is_group, user.id)

    # ── transcribe ────────────────────────────────────────────────────────────
    elif action_type == "transcribe":
        from api.routes.webhook.evolution.handles.audio import handle_transcribe_command
        await handle_transcribe_command(remote_id, message_id, {"data": {}}, user.id, group_id)

    # ── remember ──────────────────────────────────────────────────────────────
    elif action_type == "remember":
        from api.routes.webhook.evolution.handles.reminder import handle_remember_command
        dt = params.get("datetime", "")
        topic = params.get("topic", "")
        remember_text = f"{dt} {topic}".strip()
        await handle_remember_command(
            scheduler=scheduler,
            remote_id=remote_id,
            message_id=message_id,
            user_id=user.id,
            treated_text=remember_text,
            group_id=group_id,
        )

    # ── twitter ───────────────────────────────────────────────────────────────
    elif action_type == "twitter":
        from api.routes.webhook.evolution.handles.social import handle_twitter_command
        url = params.get("url", "")
        await handle_twitter_command(remote_id, url, message_id)

    # ── instagram ─────────────────────────────────────────────────────────────
    elif action_type == "instagram":
        from api.routes.webhook.evolution.handles.social import handle_instagram_command
        url = params.get("url", "")
        await handle_instagram_command(remote_id, url, message_id)

    # ── resume ────────────────────────────────────────────────────────────────
    elif action_type == "resume":
        from api.routes.webhook.evolution.handles.utility import handle_resume_command
        await handle_resume_command(remote_id, message_id, user.id, group_id)

    # ── help ──────────────────────────────────────────────────────────────────
    elif action_type == "help":
        from api.routes.webhook.evolution.handles.utility import handle_help_command
        await handle_help_command(remote_id, message_id)

    # ── model ─────────────────────────────────────────────────────────────────
    elif action_type == "model":
        from api.routes.webhook.evolution.handles.utility import handle_model_command
        await handle_model_command(remote_id, message_id, db)

    # ── consumption ───────────────────────────────────────────────────────────
    elif action_type == "consumption":
        from api.routes.webhook.evolution.handles.utility import handle_consumption_command
        if group_id:
            await handle_consumption_command(remote_id, group_id=group_id)
        else:
            await handle_consumption_command(remote_id, user_id=user.id)

    # ── favorite ──────────────────────────────────────────────────────────────
    elif action_type == "favorite":
        from api.routes.webhook.evolution.handles.favorite import handle_favorite_message
        fav_context = dict(context)
        quoted_id = params.get("message_id")
        if quoted_id:
            fav_context["quoted_message"] = str(quoted_id)
        await handle_favorite_message(remote_id=remote_id, context=fav_context, db=db)

    # ── gallery ───────────────────────────────────────────────────────────────
    elif action_type == "gallery":
        from api.routes.webhook.evolution.handles.image import handle_list_images_command
        filter_term = params.get("filter")
        if group_id:
            await handle_list_images_command(remote_id, filter_term, db, group_id=group_id)
        else:
            await handle_list_images_command(remote_id, filter_term, db, user_id=user.id)

    else:
        await logger.error("ConversationHandle", "UnknownAction", f"Unknown action type: {action_type}")
