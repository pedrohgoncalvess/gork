from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.conversation import conversation_agent
from agents.parser.conversation import parse_gork_response
from api.routes.webhook.evolution.handles.audio import handle_transcribe_command
from api.routes.webhook.evolution.handles.image import (
    handle_describe_image_command,
    handle_image_command,
    handle_picture_command,
    handle_sticker_command,
)
from api.routes.webhook.evolution.handles.reminder import handle_remember_command
from api.routes.webhook.evolution.handles.social import handle_instagram_command, handle_twitter_command
from api.routes.webhook.evolution.handles.utility import (
    handle_help_command,
    handle_model_command,
    handle_resume_command,
    handle_consumption_command
)
from api.routes.webhook.evolution.handles.favorite import handle_favorite_message
from api.routes.webhook.evolution.handles.image import handle_list_images_command
from database.models.base import User
from database.models.content import Message
from database.models.manager import Interaction
from database.operations.base import UserRepository
from database.operations.manager import InteractionRepository, ModelRepository
from external import completions
from external.evolution import send_audio, send_message
from log import logger
from tts import text_to_speech


MAX_WEB_SEARCH_DEPTH = 2

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

    await _dispatch_gork_response(
        raw_response=raw_response,
        remote_id=remote_id,
        message_id=message_id,
        user=user,
        db=db,
        db_message=db_message,
        scheduler=scheduler,
        context=context,
        group_id=group_id,
    )


async def _dispatch_gork_response(
        raw_response: str,
        remote_id: str,
        message_id: str,
        user: User,
        db: AsyncSession,
        db_message: Message,
        scheduler: AsyncIOScheduler,
        context: dict,
        group_id: Optional[int],
        web_search_depth: int = 0,
):
    try:
        parsed = await parse_gork_response(raw_response)
    except ValueError as e:
        await logger.error("ConversationHandle", "ParseError", str(e))
        await send_message(remote_id, "Desculpa, tive um problema interno. Tenta de novo?", message_id)
        return

    for action in parsed.get("actions", []):
        action_type = action.get("action")

        try:
            should_continue = await _dispatch_action(
                action_type=action_type,
                action=action,
                remote_id=remote_id,
                user=user,
                db=db,
                db_message=db_message,
                scheduler=scheduler,
                context=context,
                group_id=group_id,
                web_search_depth=web_search_depth,
            )
            if not should_continue:
                return
        except Exception as e:
            await logger.error("ConversationHandle", f"ActionError:{action_type}", str(e))


async def _run_web_search(
        db: AsyncSession,
        user: User,
        query: str,
        group_id: Optional[int],
) -> str:
    model_repo = ModelRepository(db)
    model = await model_repo.get_default_model()

    system_prompt = (
        "Use web search to answer the query with current, source-backed information. "
        "Return a concise summary in the query language. Include source names and URLs when available."
    )
    payload = {
        "model": model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": query,
            }
        ]
    }

    req = await completions(payload, is_online=True)
    result = req["choices"][0]["message"]["content"]

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=model.id,
        user_id=user.id,
        group_id=group_id,
        user_prompt=query,
        response=result,
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt
    )

    return result


async def _dispatch_action(
        action_type: str,
        action: dict,
        remote_id: str,
        user: User,
        db: AsyncSession,
        db_message: Message,
        scheduler: AsyncIOScheduler,
        context: dict,
        group_id: Optional[int],
        web_search_depth: int = 0,
) -> bool:
    params = action.get("parameters", {}) or {}

    if action_type == "message":
        await send_message(remote_id, action.get("content", ""), db_message.message_id)
        return True

    elif action_type == "audio":
        text = params.get("text", "")
        language = params.get("language", "pt")
        audio_b64 = await text_to_speech(text, language=language)
        await send_audio(remote_id, audio_b64, db_message.message_id)
        return True

    elif action_type == "sticker":

        sticker_context = dict(context)
        quoted_id = params.get("message_id")
        if quoted_id:
            sticker_context["image_quote"] = str(quoted_id)

        await handle_sticker_command(
            remote_id=remote_id,
            db_message=db_message,
            db=db,
            message_context=sticker_context,
        )
        return True

    elif action_type == "picture":
        users_requested = params.get("users", [])
        user_repo = UserRepository(db)

        picture_context = dict(context)
        resolved_mentions = []
        for name in users_requested:
            found = await user_repo.find_by_name(name)
            if found:
                resolved_mentions.append(found.src_id or found.phone_number)

        picture_context["mentions"] = resolved_mentions
        picture_context["quoted_message"] = db_message.message_id

        await handle_picture_command(remote_id=remote_id, context=picture_context, db=db)
        return True

    elif action_type == "image":
        prompt = params.get("prompt", "")
        await handle_image_command(
            remote_id=remote_id,
            user_id=user.id,
            db_message=db_message,
            context=context,
            group_id=group_id,
        )
        return True

    elif action_type == "describe":
        quoted_msg_id = params.get("message_id")
        describe_context = dict(context)
        if quoted_msg_id:
            describe_context["image_quote"] = str(quoted_msg_id)
        await handle_describe_image_command(
            remote_id=remote_id,
            user_id=user.id,
            medias=describe_context,
            db=db,
            group_id=group_id,
        )
        return True

    elif action_type == "transcribe":
        await handle_transcribe_command(remote_id, db_message.message_id, {"data": {}}, user.id, group_id)
        return True

    elif action_type == "remember":
        dt = params.get("datetime", "")
        topic = params.get("topic", "")
        remember_text = f"{dt} {topic}".strip()
        await handle_remember_command(
            scheduler=scheduler,
            remote_id=remote_id,
            message_id=db_message.message_id,
            user_id=user.id,
            treated_text=remember_text,
            group_id=group_id,
        )
        return True

    elif action_type == "web_search":
        if web_search_depth >= MAX_WEB_SEARCH_DEPTH:
            await send_message(remote_id, "Nao consegui concluir a busca agora. Tenta de novo em instantes?", db_message.message_id)
            return False

        query = params.get("query") or params.get("term") or params.get("search")
        if not query:
            await logger.error("ConversationHandle", "WebSearchError", "Missing web_search query parameter.")
            return False

        search_result = await _run_web_search(db, user, query, group_id)
        additional_context = (
            "## Web Search Result\n"
            f"Query: {query}\n\n"
            f"{search_result}"
        )
        raw_response = await conversation_agent(
            db=db,
            user_id=user.id,
            last_message_id=db_message.id,
            group_id=group_id,
            additional_context=additional_context,
        )
        await _dispatch_gork_response(
            raw_response=raw_response,
            remote_id=remote_id,
            message_id=db_message.message_id,
            user=user,
            db=db,
            db_message=db_message,
            scheduler=scheduler,
            context=context,
            group_id=group_id,
            web_search_depth=web_search_depth + 1,
        )
        return False

    elif action_type == "twitter":
        url = params.get("url", "")
        await handle_twitter_command(remote_id, url, db_message.message_id)
        return True

    elif action_type == "instagram":
        url = params.get("url", "")
        await handle_instagram_command(remote_id, url, db_message.message_id)
        return True

    elif action_type == "resume":
        await handle_resume_command(remote_id, db_message.message_id, user.id, group_id)
        return True

    elif action_type == "help":
        await handle_help_command(remote_id, db_message.message_id)
        return True

    elif action_type == "model":
        await handle_model_command(remote_id, db_message.message_id, db)
        return True

    elif action_type == "consumption":
        if group_id:
            await handle_consumption_command(remote_id, group_id=group_id)
        else:
            await handle_consumption_command(remote_id, user_id=user.id)
        return True

    elif action_type == "favorite":
        fav_context = dict(context)
        quoted_id = params.get("message_id")
        if quoted_id:
            fav_context["quoted_message"] = str(quoted_id)
        await handle_favorite_message(remote_id=remote_id, context=fav_context, db=db)
        return True

    elif action_type == "gallery":
        filter_term = params.get("filter")
        if group_id:
            await handle_list_images_command(remote_id, filter_term, db, group_id=group_id)
        else:
            await handle_list_images_command(remote_id, filter_term, db, user_id=user.id)
        return True

    else:
        await logger.error("ConversationHandle", "UnknownAction", f"Unknown action type: {action_type}")
        return True
