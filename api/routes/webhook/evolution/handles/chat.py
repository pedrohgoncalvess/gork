import json
from typing import Any, Optional

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
from database.operations.content import MessageRepository
from database.operations.manager import InteractionRepository, ModelRepository
from external import completions
from external.evolution import send_audio, send_message
from llm_access import (
    get_group_messages,
    get_group_users,
    get_user_images,
    get_user_messages,
    search_messages,
)
from log import logger
from tts import text_to_speech


MAX_WEB_SEARCH_DEPTH = 2
MAX_DATABASE_QUERY_ITERATIONS = 10
DATABASE_QUERY_STOP_ITERATION = 7

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
        database_query_iteration: int = 0,
        database_context: str = "",
):
    try:
        parsed = await parse_gork_response(raw_response)
    except ValueError as e:
        await logger.error("ConversationHandle", "ParseError", str(e))
        await send_message(remote_id, "Desculpa, tive um problema interno. Tenta de novo?", message_id)
        return

    queries = parsed.get("queries", [])
    if queries:
        await _continue_with_database_queries(
            parsed=parsed,
            remote_id=remote_id,
            message_id=message_id,
            user=user,
            db=db,
            db_message=db_message,
            scheduler=scheduler,
            context=context,
            group_id=group_id,
            web_search_depth=web_search_depth,
            database_query_iteration=database_query_iteration,
            database_context=database_context,
        )
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
                database_query_iteration=database_query_iteration,
                database_context=database_context,
            )
            if not should_continue:
                return
        except Exception as e:
            await logger.error("ConversationHandle", f"ActionError:{action_type}", str(e))


async def _continue_with_database_queries(
        parsed: dict,
        remote_id: str,
        message_id: str,
        user: User,
        db: AsyncSession,
        db_message: Message,
        scheduler: AsyncIOScheduler,
        context: dict,
        group_id: Optional[int],
        web_search_depth: int,
        database_query_iteration: int,
        database_context: str,
) -> None:
    next_iteration = database_query_iteration + 1
    if next_iteration >= DATABASE_QUERY_STOP_ITERATION:
        await logger.error(
            "ConversationHandle",
            "DatabaseQueryLimit",
            f"Stopped database query recursion at iteration {next_iteration}."
        )
        await send_message(
            remote_id,
            "Nao consegui concluir essa consulta com seguranca. Tenta pedir de um jeito mais especifico?",
            message_id,
        )
        return

    if next_iteration > MAX_DATABASE_QUERY_ITERATIONS:
        await logger.error(
            "ConversationHandle",
            "DatabaseQueryLimit",
            f"Exceeded max database query iterations: {MAX_DATABASE_QUERY_ITERATIONS}."
        )
        return

    query_results = []
    for query in parsed.get("queries", []):
        query_results.append(
            await _execute_database_query(
                db=db,
                group_id=group_id,
                query=query,
            )
        )

    context_chunk = _format_database_query_context(
        iteration=next_iteration,
        reasoning=parsed.get("reasoning", ""),
        next_call_instruction=parsed.get("next_call_instruction", ""),
        query_results=query_results,
    )
    additional_context = "\n\n".join(
        part for part in [database_context, context_chunk] if part
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
        message_id=message_id,
        user=user,
        db=db,
        db_message=db_message,
        scheduler=scheduler,
        context=context,
        group_id=group_id,
        web_search_depth=web_search_depth,
        database_query_iteration=next_iteration,
        database_context=additional_context,
    )


async def _execute_database_query(
        db: AsyncSession,
        group_id: Optional[int],
        query: dict,
) -> dict[str, Any]:
    query_type = query.get("query_type")
    params = _query_parameters(query)

    if group_id is None:
        return {
            "query_type": query_type,
            "parameters": params,
            "error": "Database queries are only available inside a group context.",
        }

    try:
        if query_type == "get_group_users":
            result = await get_group_users(
                db=db,
                group_id=group_id,
                query=params.get("query") or params.get("search") or params.get("name"),
                limit=params.get("limit"),
            )
        elif query_type in {"get_group_messages", "get_messages"}:
            result = await get_group_messages(
                db=db,
                group_id=group_id,
                query=params.get("query") or params.get("search") or params.get("text"),
                limit=params.get("limit"),
                user_id=_optional_int_param(params, "user_id"),
                media_type=params.get("media_type"),
                include_deleted=bool(params.get("include_deleted", False)),
            )
        elif query_type == "get_user_messages":
            user_id = _required_user_id(params)
            result = await get_user_messages(
                db=db,
                group_id=group_id,
                user_id=user_id,
                query=params.get("query") or params.get("search") or params.get("text"),
                limit=params.get("limit"),
                include_deleted=bool(params.get("include_deleted", False)),
            )
        elif query_type == "search_messages":
            search_query = params.get("query") or params.get("search") or params.get("text")
            if not search_query:
                raise ValueError("Missing required parameter: query")
            result = await search_messages(
                db=db,
                group_id=group_id,
                query=search_query,
                limit=params.get("limit"),
                user_id=_optional_int_param(params, "user_id"),
                media_type=params.get("media_type"),
                include_deleted=bool(params.get("include_deleted", False)),
            )
        elif query_type == "get_user_images":
            user_id = _required_user_id(params)
            result = await get_user_images(
                db=db,
                group_id=group_id,
                user_id=user_id,
                limit=params.get("limit"),
            )
        else:
            raise ValueError(f"Unknown query_type: {query_type}")

        return {
            "query_type": query_type,
            "parameters": params,
            "result": result,
        }
    except Exception as error:
        await logger.error("ConversationHandle", "DatabaseQueryError", str(error))
        return {
            "query_type": query_type,
            "parameters": params,
            "error": str(error),
        }


def _query_parameters(query: dict) -> dict[str, Any]:
    params = dict(query.get("parameters", {}) or {})
    params.pop("group_id", None)
    return params


def _optional_int_param(params: dict[str, Any], key: str) -> int | None:
    value = params.get(key)
    if value is None or value == "":
        return None
    return int(value)


def _required_user_id(params: dict[str, Any]) -> int:
    user_id = _optional_int_param(params, "user_id")
    if user_id is None:
        raise ValueError("Missing required parameter: user_id")
    return user_id


def _format_database_query_context(
        iteration: int,
        reasoning: str,
        next_call_instruction: str,
        query_results: list[dict[str, Any]],
) -> str:
    return (
        f"## Database Query Iteration {iteration}\n"
        f"Model reasoning before query:\n{reasoning or '[EMPTY]'}\n\n"
        f"Next call instruction from model:\n{next_call_instruction or '[EMPTY]'}\n\n"
        "[DATABASE QUERY RESULTS]\n"
        f"{json.dumps(query_results, ensure_ascii=False, default=str)}"
    )


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
        database_query_iteration: int = 0,
        database_context: str = "",
) -> bool:
    params = action.get("parameters", {}) or {}
    message_repo = MessageRepository(db)

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
        message_id = params.get("message_id")
        referred_message = await message_repo.find_by_id(message_id)

        await handle_sticker_command(
            remote_id=remote_id,
            db_message=referred_message,
            db=db,
        )
        return True

    elif action_type == "picture":
        users_requested = params.get("users", [])
        user_repo = UserRepository(db)

        resolved_mentions = []
        for user_id in users_requested:
            user = await user_repo.find_by_id(user_id)
            if user:
                resolved_mentions.append(user)

        await handle_picture_command(remote_id=remote_id, mentions=resolved_mentions)
        return True

    elif action_type == "image":
        message_id = params.get("message_id")
        referred_message = await message_repo.find_by_id(message_id)

        await handle_image_command(
            remote_id=remote_id,
            user_id=user.id,
            db_message=referred_message,
        )
        return True

    elif action_type == "describe":
        message_id = params.get("message_id")
        referred_message = await message_repo.find_by_id(message_id)
        await handle_describe_image_command(
            remote_id=remote_id,
            user_id=user.id,
            db=db,
            group_id=group_id,
            db_message=referred_message,
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
            await send_message(remote_id, "Nao consegui concluir a busca agora. Tenta de novo outra hora")
            return False

        query = params.get("query") or params.get("term") or params.get("search")
        if not query:
            await logger.error("ConversationHandle", "WebSearchError", "Missing web_search query parameter.")
            return False

        search_result = await _run_web_search(db, user, query, group_id)
        web_search_context = (
            "## Web Search Result\n"
            f"Query: {query}\n\n"
            f"{search_result}"
        )
        additional_context = "\n\n".join(
            part for part in [database_context, web_search_context] if part
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
            database_query_iteration=database_query_iteration,
            database_context=database_context,
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
