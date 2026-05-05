from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.manager import Interaction
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from database.operations.manager import AgentRepository, InteractionRepository, ModelRepository
from external import completions
from external.evolution import download_media
from log import logger
from utils import get_env_var


def _message_sender_name(message, gork_user_id: Optional[int]) -> str:
    if message.sender and gork_user_id and message.sender.id == gork_user_id:
        return "Voce"
    if message.sender and message.sender.name:
        return message.sender.name
    return "Usuario Desconhecido."


def _format_timestamp(created_at: datetime) -> str:
    if created_at.date() != datetime.now().date():
        return created_at.strftime("%d/%m/%Y %H:%M")
    return created_at.strftime("%H:%M")


def _format_message(message, gork_user_id: Optional[int]) -> str:
    sender_name = _message_sender_name(message, gork_user_id)
    timestamp = _format_timestamp(message.created_at)
    content = message.content or "[midia sem texto]"
    return f"[{message.id}] {sender_name} - [{timestamp}]: {content}"


async def describe_image_agent(
        db: AsyncSession,
        user_id: int,
        message_id: str,
        image_base64: Optional[str] = None,
        group_id: Optional[int] = None,
) -> str:
    model_repo = ModelRepository(db)
    agent_repo = AgentRepository(db)
    message_repo = MessageRepository(db)
    user_repo = UserRepository(db)

    agent = await agent_repo.find_by_name("describe-image")
    if not agent:
        await logger.error("Agent", "DescribeImage", "Describe image agent not found.")
        return ""

    model = await model_repo.find_by_id(agent.model_id)
    if not model:
        await logger.error("Agent", "DescribeImage", f"Model not found for agent {agent.name}.")
        return ""

    user_gork = await user_repo.find_by_phone(get_env_var("EVOLUTION_INSTANCE_NUMBER"))
    user_sender = await user_repo.find_by_id(user_id)

    if group_id:
        messages = await message_repo.find_by_group(group_id, 10)
    else:
        messages = await message_repo.find_by_sender(user_id, 5)

    gork_user_id = user_gork.id if user_gork else None
    messages_rel = {message.id: message for message in messages}

    formatted_messages = []
    existing_messages = set()
    for msg in messages:
        content = msg.content or ""
        if content and content.lower() in existing_messages:
            continue

        formatted_messages.append(_format_message(msg, gork_user_id))
        if content:
            existing_messages.add(content.lower())

    image_message = next((message for message in messages if message.message_id == message_id), None)
    if not image_message:
        image_message = await message_repo.find_by_message_id(message_id)

    quoted_message = (
        messages_rel.get(image_message.quoted_message_id)
        if image_message and image_message.quoted_message_id
        else None
    )

    if image_message and gork_user_id and image_message.user_id == gork_user_id:
        image_sender = "Voce"
    elif image_message and image_message.user_id:
        image_sender_user = await user_repo.find_by_id(image_message.user_id)
        image_sender = image_sender_user.name if image_sender_user and image_sender_user.name else "Usuario Desconhecido."
    else:
        image_sender = user_sender.name if user_sender and user_sender.name else "Usuario Desconhecido."

    image_content = image_message.content if image_message and image_message.content else "[imagem sem legenda]"
    image_timestamp = _format_timestamp(image_message.created_at) if image_message else datetime.now().strftime("%H:%M")
    quoted_context = f"Mensagem quotada pela imagem: {quoted_message.content}\n" if quoted_message else ""

    current_context = (
        f"{quoted_context}"
        f"Mensagem da imagem: {image_sender} - [{image_timestamp}]: {image_content}\n"
    )

    conversation_history = "\n".join(formatted_messages)
    system_prompt = agent.prompt.replace("$$CONVERSATION_HISTORY$$", conversation_history)

    if not image_base64:
        image_base64, _ = await download_media(message_id)

    messages_content = [
        {
            "type": "text",
            "text": current_context,
        },
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_base64}",
            },
        },
    ]

    payload = {
        "model": model.openrouter_id,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": messages_content,
            },
        ],
    }

    req = await completions(payload)
    resp = req["choices"][0]["message"]["content"]

    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=model.id,
        user_id=user_id,
        group_id=group_id,
        agent_id=agent.id,
        user_prompt=current_context,
        response=resp,
        input_tokens=req["usage"]["prompt_tokens"],
        output_tokens=req["usage"]["completion_tokens"],
        system_behavior=system_prompt,
    )

    return resp
