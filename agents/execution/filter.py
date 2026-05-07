import json
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.parser.filter import parse_filter_response
from database.models.content import Message
from database.models.manager import Interaction
from database.operations.base import UserRepository
from database.operations.manager import AgentRepository, InteractionRepository, ModelConversationRepository
from external import completions
from log import logger
from utils import get_env_var


def _sender_name(message: Message, gork_user_id: int | None) -> str:
    sender = getattr(message, "sender", None)

    if sender and gork_user_id and sender.id == gork_user_id:
        return "Voce"
    if sender and sender.name:
        return sender.name
    return "Usuario Desconhecido."


def _format_timestamp(created_at: datetime) -> str:
    if created_at.date() != datetime.now().date():
        return created_at.strftime("%d/%m/%Y %H:%M")
    return created_at.strftime("%H:%M")


def _format_message(message: Message, gork_user_id: int | None) -> str:
    sender_name = _sender_name(message, gork_user_id)
    timestamp = _format_timestamp(message.created_at)
    content = message.content or "[midia sem texto]"
    return f"[{message.id}] {sender_name} - [{timestamp}]: {content}"


async def filter_agent(
        db: AsyncSession,
        messages: list[Message],
) -> dict[str, Any]:
    if not messages:
        return {
            "reasoning": "No messages were provided for filtering.",
            "should_respond": False,
            "confidence": "high",
            "trigger_type": None,
        }

    agent_repo = AgentRepository(db)
    user_repo = UserRepository(db)
    model_conversation_repo = ModelConversationRepository(db)

    agent = await agent_repo.find_by_name("filter")
    if not agent:
        await logger.error("Agent", "Filter", "Filter agent not found.")
        return {
            "reasoning": "Filter agent is not configured.",
            "should_respond": False,
            "confidence": "low",
            "trigger_type": None,
        }

    last_message = messages[-1]
    model = await model_conversation_repo.resolve_agent_model(
        agent,
        user_id=last_message.user_id,
        group_id=last_message.group_id,
    )
    if not model:
        await logger.error("Agent", "Filter", f"Model not found for agent {agent.name}.")
        return {
            "reasoning": "Filter agent model is not configured.",
            "should_respond": False,
            "confidence": "low",
            "trigger_type": None,
        }

    user_gork = await user_repo.find_by_phone(get_env_var("EVOLUTION_INSTANCE_NUMBER"))
    gork_user_id = user_gork.id if user_gork else None

    formatted_messages = []
    existing_messages = set()
    for msg in messages:
        content = msg.content or ""
        if content and content.lower() in existing_messages:
            continue

        formatted_messages.append(_format_message(msg, gork_user_id))
        if content:
            existing_messages.add(content.lower())

    conversation_history = "\n".join(formatted_messages)
    system_prompt = agent.prompt

    payload = {
        "model": model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": conversation_history,
            },
        ],
    }

    req = await completions(payload)
    raw_response = req["choices"][0]["message"]["content"]
    response = await parse_filter_response(raw_response)

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=model.id,
        user_id=last_message.user_id,
        group_id=last_message.group_id,
        agent_id=agent.id,
        user_prompt=conversation_history,
        response=json.dumps(response, ensure_ascii=False),
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt,
    )

    return response
