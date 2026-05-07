from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.manager import Interaction
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from database.operations.manager import AgentRepository, InteractionRepository, ModelConversationRepository
from external import completions
from log import logger
from utils import get_env_var


async def conversation_agent(
        db: AsyncSession,
        user_id: int,
        last_message_id: int,
        group_id: Optional[int] = None,
        additional_context: str = "",
) -> str:
    agent_repo = AgentRepository(db)
    model_conversation_repo = ModelConversationRepository(db)
    message_repo = MessageRepository(db)
    user_repo = UserRepository(db)

    user_gork = await user_repo.find_by_phone(get_env_var("EVOLUTION_INSTANCE_NUMBER"))
    user_sender = await user_repo.find_by_id(user_id)

    if not user_gork:
        await logger.error("Agent", "Generic", "Instance user not found.")
        return ""

    if group_id:
        messages = await message_repo.find_by_group(group_id, 80)
    else:
        messages = await message_repo.find_by_sender(user_id, 40)

    messages_rel = {message.id: message for message in messages}

    formatted_messages = []
    existing_messages = []
    for msg in messages:
        if msg.sender.id == user_gork.id:
            sender_name = "Você"
        elif msg.sender.name:
            sender_name = msg.sender.name
        else:
            sender_name = "Usuário Desconhecido."

        content = msg.content or ""

        if content.lower() in existing_messages:
            continue

        msg_date = msg.created_at.date()
        today = datetime.now().date()

        if msg_date != today:
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
        else:
            timestamp = msg.created_at.strftime('%H:%M')

        formatted_messages.append(f"[{msg.id}] {sender_name} - [{timestamp}]: {content}")
        existing_messages.append(content.lower())

    last_message = messages_rel.get(last_message_id)
    quoted_message = messages_rel.get(last_message.quoted_message_id) if last_message else None
    current_message = (
            (f"Mensagem quotada: {quoted_message.content}\n" if quoted_message else "") +
            f"{user_sender.name} - [{datetime.now().strftime('%H:%M')}]: {last_message.content if last_message else ''}"
    )

    agent = await agent_repo.find_by_name("conversation")
    if not agent:
        await logger.error("Agent", "Conversation", "Conversation agent not found.")
        return ""

    model = await model_conversation_repo.resolve_agent_model(agent, user_id=user_id, group_id=group_id)
    if not model:
        await logger.error("Agent", "Conversation", f"Model not found for agent {agent.name}.")
        return ""

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))

    conversation_history = "\n".join(formatted_messages)
    system_prompt = agent.prompt.replace("$$CONVERSATION_HISTORY$$", conversation_history)
    system_prompt = system_prompt.replace("$$ADDITIONAL_CONTEXT$$", additional_context)
    system_prompt = system_prompt.replace("$$CURRENT_DATE$$", now.strftime("%B %d, %Y"))

    payload_term_formatter = {
        "model": model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": current_message,
            }
        ]
    }

    req = await completions(payload_term_formatter)
    resp = req["choices"][0]["message"]["content"]

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=model.id,
        user_id=user_id,
        group_id=group_id,
        agent_id=agent.id,
        user_prompt=current_message,
        response=resp,
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt
    )

    return resp
