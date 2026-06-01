import json
import re
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
from utils import INSTANCE_NUMBER, project_root
from database.operations.content.sup_media import SupMediaRepository
import yaml
from pathlib import Path


def replace_mentions(content: str, users_map: dict) -> str:
    if not content:
        return content
    mentions = re.findall(r'@(\d{5,})', content)
    for mention in set(mentions):
        if mention in users_map:
            content = content.replace(f"@{mention}", f"@{users_map[mention]}")
    return content


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

    users_map = {}
    if group_id:
        users_group = await user_repo.find_users_by_group_id(group_id)
        raw_messages = await message_repo.find_by_group(group_id, 80)
        messages = []

        users_map = {u.src_id.split('@')[0]: (u.name or "Usuário") for u in users_group if u.src_id}

        for message in raw_messages:
            message.content = replace_mentions(message.content, users_map)
            
            if not message.content:
                continue

            messages.append(message)
    else:
        messages = await message_repo.find_by_sender(user_id, 40)

    user_gork = await user_repo.find_by_phone(INSTANCE_NUMBER)
    user_sender = await user_repo.find_by_id(user_id)

    if not user_gork:
        await logger.error("Agent", "Generic", "Instance user not found.")
        return ""

    messages_rel = {message.id: message for message in messages}

    formatted_messages = []
    for msg in messages:
        if msg.sender.id == user_gork.id:
            sender_name = "Você"
        elif msg.sender.name:
            sender_name = msg.sender.name
        else:
            sender_name = "Usuário Desconhecido."

        content = msg.content or ""

        msg_date = msg.created_at.date()
        today = datetime.now().date()

        if msg_date != today:
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
        else:
            timestamp = msg.created_at.strftime('%H:%M')

        formatted_messages.append(f"[{msg.id}] {sender_name} - [{timestamp}]: {content}")

    last_message = messages_rel.get(last_message_id)
    if last_message:
        last_message.content = replace_mentions(last_message.content, users_map)
        
    quoted_message = messages_rel.get(last_message.quoted_message_id) if last_message else None
    if quoted_message:
        quoted_message.content = replace_mentions(quoted_message.content, users_map)

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

    await logger.info(
        "Agent",
        "Conversation",
        f"Messages: {formatted_messages}. Current message: {current_message},  group_id={group_id}"
    )

    now = datetime.now(ZoneInfo("America/Sao_Paulo"))

    conversation_history = "\n".join(formatted_messages)
    
    sup_media_repo = SupMediaRepository(db)
    all_media = await sup_media_repo.find_all(limit=1000)
    
    metadata_path = Path(project_root) / "assets" / "metadata.yaml"
    descriptions = {}
    if metadata_path.exists():
        with open(metadata_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            for m_type in ("audio", "video", "image"):
                for item in config.get(m_type) or []:
                    descriptions[item.get("name")] = item.get("description", "").strip()

    media_lines = []
    for media in all_media:
        desc = descriptions.get(media.name, "Nenhuma descrição.")
        media_lines.append(f"[{media.id}] - {media.type} - {media.name} - {desc}")
    available_media_str = "\n".join(media_lines) if media_lines else "Nenhuma mídia disponível no momento."

    system_prompt = agent.prompt.replace("$$CONVERSATION_HISTORY$$", conversation_history)
    system_prompt = system_prompt.replace("$$AVAILABLE_MEDIA$$", available_media_str)
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

    if agent.response_format:
        payload_term_formatter["response_format"] = json.loads(agent.response_format)

    await logger.info(
        "Agent",
        "Conversation",
        f"Calling completions API with model {model.openrouter_id}. Prompt chars: {len(system_prompt)}. User msg: '{current_message}'"
    )

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
