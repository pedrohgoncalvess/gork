import json
from datetime import datetime
from uuid import uuid4

from database import PgConnection
from database.models.base import User
from database.models.content import Message
from database.operations.base.user import UserRepository
from database.operations.content.message import MessageRepository
from services import manage_interaction
from utils import get_env_var


async def generic_conversation(contact_id: int, user_name: str, last_message: str, user_id: int, message_context: dict, is_group: bool = True) -> dict:
    quoted_text = message_context["text_quote"] if "text_quote" in message_context.keys() else None

    async with PgConnection() as db:
        user_repo = UserRepository(User, db)
        user_gork = await user_repo.find_by_name("Gork")
        # TODO: This SHOULD BE removed later. A better solution has to be implemented.
        if not user_gork:
            user_gork = await user_repo.insert(User(name="Gork", src_id=str(uuid4()), phone_number=get_env_var("EVOLUTION_INSTANCE_NUMBER")))

        message_repo = MessageRepository(Message, db)
        if is_group:
            messages = await message_repo.find_by_group(contact_id, 20)
        else:
            messages = await message_repo.find_by_sender(contact_id, 15)

        formatted_messages = []
        existing_messages = []
        for msg in messages:
            sender_name = msg.sender.name or msg.sender.phone_jid or "Usuário Desconhecido"
            content = msg.content or ""

            if content.lower() in existing_messages:
                continue

            msg_date = msg.created_at.date()
            today = datetime.now().date()

            if msg_date != today:
                timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            else:
                timestamp = msg.created_at.strftime('%H:%M')

            formatted_messages.append(f"{sender_name}: {content} - {timestamp}")
            existing_messages.append(content.lower())

        message = (
                (f"Mensagem quotada: {quoted_text}\n" if quoted_text else "") +
                "Última mensagem enviada e que dever ser respondida:\n"
                f"{user_name}: {last_message} - {datetime.now().strftime('%H:%M')}"
        )

        formatted_messages.append(message)
        final_message = "\n".join(formatted_messages)

        resp = await manage_interaction(db, final_message, agent_name="generic", user_id=user_id, group_id=contact_id if is_group else None)
        formatted_resp = json.loads(f"""{resp}""")

        _ = await message_repo.insert(Message(
            message_id=str(uuid4()),
            group_id = contact_id if is_group else None,
            user_id=user_gork.id,
            content=formatted_resp.get("text"),
            created_at=datetime.now()
        ))

        return formatted_resp