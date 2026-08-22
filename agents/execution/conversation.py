import json
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.manager import Interaction
from database.operations.base import UserRepository
from database.operations.content import MediaRepository, MessageRepository
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


def _message_body(message, media_by_id: dict[int, object]) -> str:
    content = message.content or ""
    if content:
        return content
    if not message.media_id:
        return ""

    media = media_by_id.get(message.media_id)
    media_type = media.type if media and media.type else "unknown"
    description = media.description.strip() if media and media.description else ""
    if description:
        return f"[Media: {media_type}; description: {description[:600]}]"
    return f"[Media: {media_type}]"


def _format_direct_message_content(
        message,
        messages_by_id: dict[int, object],
        media_by_id: Optional[dict[int, object]] = None,
) -> str:
    """Format one DM turn while preserving actionable message metadata."""
    media_by_id = media_by_id or {}
    content = _message_body(message, media_by_id)
    if not content:
        return ""

    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S") if message.created_at else "unknown"
    parts = [f"[message_id={message.id}; sent_at={timestamp}]"]

    if message.quoted_message_id:
        quoted = messages_by_id.get(message.quoted_message_id)
        if quoted:
            quoted_content = _message_body(quoted, media_by_id)
            if quoted_content:
                parts.append(f"[replying_to={quoted.id}: {quoted_content}]")
        else:
            parts.append(f"[replying_to_message_id={message.quoted_message_id}]")

    parts.append(content)
    return "\n".join(parts)


def _format_group_message_content(
        message,
        messages_by_id: dict[int, object],
        media_by_id: dict[int, object],
        users_map: dict[str, str],
) -> str:
    content = replace_mentions(_message_body(message, media_by_id), users_map)
    if not content:
        return ""

    sender_name = message.sender.name if message.sender and message.sender.name else "Usuário Desconhecido"
    timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S") if message.created_at else "unknown"
    parts = [f"[message_id={message.id}; sender={sender_name}; sent_at={timestamp}]"]

    if message.quoted_message_id:
        quoted = messages_by_id.get(message.quoted_message_id)
        if quoted:
            quoted_sender = quoted.sender.name if quoted.sender and quoted.sender.name else "Usuário Desconhecido"
            quoted_content = replace_mentions(_message_body(quoted, media_by_id), users_map)
            parts.append(
                f"[replying_to={quoted.id}; sender={quoted_sender}: "
                f"{quoted_content or '[content unavailable]'}]"
            )
        else:
            parts.append(f"[replying_to_message_id={message.quoted_message_id}]")

    parts.append(content)
    return "\n".join(parts)


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

    last_message = await message_repo.find_by_id(last_message_id)
    if not last_message:
        await logger.error("Agent", "Conversation", f"Message {last_message_id} not found.")
        return ""

    user_gork = await user_repo.find_by_phone(INSTANCE_NUMBER)
    user_sender = await user_repo.find_by_id(user_id)

    if not user_gork:
        await logger.error("Agent", "Generic", "Instance user not found.")
        return ""

    users_map = {}
    if group_id:
        users_group = await user_repo.find_users_by_group_id(group_id)
        raw_messages = await message_repo.find_by_group(group_id, 50, until=last_message)
        users_map = {u.src_id.split('@')[0]: (u.name or "Usuário") for u in users_group if u.src_id}
    else:
        raw_messages = await message_repo.find_private_conversation(
            user_id=user_id,
            gork_user_id=user_gork.id,
            limit=40,
            until=last_message,
        )

    # Sort raw_messages chronologically (oldest message first, newest message last)
    raw_messages = sorted(raw_messages, key=lambda m: (m.created_at or datetime.min, m.id))
    messages_rel = {msg.id: msg for msg in raw_messages}

    missing_quoted_ids = {
        msg.quoted_message_id
        for msg in raw_messages
        if msg.quoted_message_id and msg.quoted_message_id not in messages_rel
    }
    for quoted_message in await message_repo.find_by_ids(list(missing_quoted_ids)):
        if quoted_message.group_id == group_id:
            messages_rel[quoted_message.id] = quoted_message

    media_repo = MediaRepository(db)
    media_ids = {msg.media_id for msg in messages_rel.values() if msg.media_id}
    media_by_id = {
        media.id: media
        for media in await media_repo.find_by_ids(list(media_ids))
    }

    # Exclude last_message from system prompt conversation history to prevent duplication
    history_messages = [msg for msg in raw_messages if msg.id != last_message_id]

    formatted_messages = []
    for msg in history_messages:
        content = replace_mentions(msg.content, users_map) if msg.content else ""
        if not content:
            if msg.media_id:
                content = "[Mídia / Imagem / Áudio]"
            else:
                continue

        if msg.sender and msg.sender.id == user_gork.id:
            sender_name = "Você"
        elif msg.sender and msg.sender.name:
            sender_name = msg.sender.name
        else:
            sender_name = "Usuário Desconhecido"

        msg_date = msg.created_at.date() if msg.created_at else datetime.now().date()
        today = datetime.now().date()

        if msg_date != today:
            timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M') if msg.created_at else ""
        else:
            timestamp = msg.created_at.strftime('%H:%M') if msg.created_at else ""

        quoted_str = ""
        if msg.quoted_message_id:
            quoted_msg = messages_rel.get(msg.quoted_message_id)
            if not quoted_msg:
                quoted_msg = await message_repo.find_by_id(msg.quoted_message_id)
            if quoted_msg:
                if quoted_msg.sender and quoted_msg.sender.id == user_gork.id:
                    quoted_sender_name = "Você"
                elif quoted_msg.sender and quoted_msg.sender.name:
                    quoted_sender_name = quoted_msg.sender.name
                else:
                    quoted_sender_name = "Usuário Desconhecido"
                q_content = replace_mentions(quoted_msg.content, users_map) if quoted_msg.content else "[Mídia]"
                quoted_str = f"Mensagem quotada: [{quoted_sender_name}] -> {q_content}\n"

        formatted_messages.append(f"{quoted_str}[{msg.id}] {sender_name} - [{timestamp}]: {content}")

    quoted_str_last = ""
    if last_message and last_message.quoted_message_id:
        quoted_msg = messages_rel.get(last_message.quoted_message_id)
        if not quoted_msg:
            quoted_msg = await message_repo.find_by_id(last_message.quoted_message_id)
        if quoted_msg:
            if quoted_msg.sender and quoted_msg.sender.id == user_gork.id:
                quoted_sender_name = "Você"
            elif quoted_msg.sender and quoted_msg.sender.name:
                quoted_sender_name = quoted_msg.sender.name
            else:
                quoted_sender_name = "Usuário Desconhecido"
            q_content = replace_mentions(quoted_msg.content, users_map) if quoted_msg.content else "[Mídia]"
            quoted_str_last = f"Mensagem quotada: [{quoted_sender_name}] -> {q_content}\n"

    last_content = replace_mentions(last_message.content, users_map) if last_message and last_message.content else ""
    if not last_content and last_message and last_message.media_id:
        last_content = "[Mídia / Imagem / Áudio]"

    sender_display_name = user_sender.name if user_sender and user_sender.name else "Usuário"
    last_msg_id_str = f"[{last_message.id}] " if last_message else ""
    current_message = (
        f"{quoted_str_last}"
        f"{last_msg_id_str}{sender_display_name} - [{datetime.now().strftime('%H:%M')}]: {last_content}"
    )

    agent_name = "conversation-group" if group_id else "conversation-dm"
    agent = await agent_repo.find_by_name(agent_name)
    if not agent:
        await logger.error("Agent", "Conversation", f"Agent {agent_name} not found.")
        return ""

    # Keep existing per-user model overrides attached to the original
    # conversation agent while using the smaller DM-specific prompt.
    model_agent = agent
    model_agent = await agent_repo.find_by_name("conversation") or agent

    model = await model_conversation_repo.resolve_agent_model(
        model_agent,
        user_id=user_id,
        group_id=group_id,
    )
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

    request_messages = [{"role": "system", "content": system_prompt}]
    for msg in history_messages:
        if group_id:
            content = _format_group_message_content(msg, messages_rel, media_by_id, users_map)
        else:
            content = _format_direct_message_content(msg, messages_rel, media_by_id)
        if not content:
            continue
        request_messages.append({
            "role": "assistant" if msg.user_id == user_gork.id else "user",
            "content": content,
        })

    if group_id:
        latest_content = _format_group_message_content(
            last_message,
            messages_rel,
            media_by_id,
            users_map,
        )
    else:
        latest_content = _format_direct_message_content(last_message, messages_rel, media_by_id)
    request_messages.append({"role": "user", "content": latest_content})

    payload_term_formatter = {
        "model": model.openrouter_id,
        "messages": request_messages,
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
