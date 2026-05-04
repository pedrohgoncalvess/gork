import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Message
from database.operations.content import MessageRepository
from external.evolution import send_message


async def handle_favorite_message(
    remote_id: str, context: dict[str, any],
    db: AsyncSession
):
    message_id = context.get("quoted_message")
    message_repo = MessageRepository(db)
    message = await message_repo.set_is_favorite(message_id)

    feedback_message = "✅ Mensagem favoritada." if message else "❌ Houve um erro ao favoritar a mensagem."

    await send_message(remote_id, feedback_message)
    return


async def handle_list_favorites_message(
        remote_id: str, db: AsyncSession,
        message_id: str, user_id: Optional[int] = None,
        group_id: Optional[int] = None, last_days: Optional[int] = None,
        user_name: Optional[str] = None
):
    message_repo = MessageRepository(db)
    favorites = await message_repo.find_favorites_messages(
        last_days=last_days,
        group_id=group_id,
        user_name=user_name,
        user_id=user_id if not group_id else None
    )

    if not favorites:
        no_favorites_text = (
            "⭐ *MENSAGENS FAVORITAS*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Nenhuma mensagem favorita encontrada.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await send_message(remote_id, no_favorites_text)
        return

    favorites_parts = [
        "⭐ *MENSAGENS FAVORITAS*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for fav in favorites:
        sender_name = fav.sender.name if fav.sender else "Desconhecido"
        date_str = fav.created_at.strftime("%d/%m/%Y %H:%M")
        content = fav.content if fav.content else "_[sem conteúdo]_"

        if len(content) > 100:
            content = content[:100] + "..."

        favorites_parts.append(
            f"`{fav.message_id}`\n"
            f"*{sender_name}:* {content} _{date_str}_"
        )
        favorites_parts.append("")

    favorites_parts.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"_📊 {len(favorites)} mensagem{'s' if len(favorites) != 1 else ''}_"
    ])

    favorites_message = "\n".join(favorites_parts)
    await send_message(remote_id, favorites_message, message_id)


async def handle_remove_favorite(
        remote_id: str, db: AsyncSession,
        conversation: str, user_id: Optional[int] = None,
        group_id: Optional[int] = None
):
    message_repo = MessageRepository(db)
    pattern = r"id:([^\s]+)"
    match_conversation = re.search(pattern, conversation)
    if match_conversation:
        message_id = match_conversation.group(1)
    else:
        await send_message(remote_id, "Utilize o comando !remove passando id:{id da mensagem}.")
        return

    message = await message_repo.find_by_message_id(message_id)

    if not message or (message.group_id != group_id and message.user_id != user_id):
        message = "Não foi encontrada nenhuma mensagem favoritada."
        await send_message(remote_id, message)
        return

    await message_repo.remove_favorite_message(message_id)
    await send_message(remote_id, "Mensagem removida dos favoritos.")
    return
