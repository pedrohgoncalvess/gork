from datetime import datetime, timedelta

from database import PgConnection
from database.models.content import Message
from database.models.manager import Model, Command
from database.models.manager.interaction import Interaction
from database.operations.content.message import MessageRepository
from database.operations.manager.command import CommandRepository
from database.operations.manager.interaction import InteractionRepository
from database.operations.manager.model import ModelRepository
from external import completions


async def get_resume_conversation(user_id: int, contact_id: int = None, group_id: int = None) -> str:

    async with PgConnection() as db:

        model_repo = ModelRepository(Model, db)
        command_repo = CommandRepository(Command, db)

        if contact_id:
            commands = await command_repo.find_by(
                user_id=user_id, contact_id=contact_id,
                command="resume"
            )
        else:
            commands = await command_repo.find_by(
                user_id=user_id, group_id=group_id,
                command="resume"
            )

        recent_commands = [
            cmd for cmd in commands
            if cmd.inserted_at >= datetime.now() - timedelta(hours=2)
        ]

        if len(recent_commands) > 0:
            most_recent = max(recent_commands, key=lambda cmd: cmd.inserted_at)

            time_diff = most_recent.inserted_at - datetime.now()

            hours = int(time_diff.total_seconds() // 3600)
            minutes = int((time_diff.total_seconds() % 3600) // 60)

            time_str = f"{hours:02d}:{minutes:02d}"

            return f"Executei esse comando tem {time_str}hr"

        model = await model_repo.get_default_model()

        message_repo = MessageRepository(Message, db)
        messages = await message_repo.find_by_group(group_id, 100)

        formatted_messages = []

        for msg in messages:
            sender_name = msg.sender.name or msg.sender.phone_jid or "Usuário Desconhecido"
            content = msg.content or ""

            msg_date = msg.created_at.date()
            today = datetime.now().date()

            if msg_date != today:
                timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
            else:
                timestamp = msg.created_at.strftime('%H:%M')

            formatted_messages.append(f"{sender_name}: {content} - {timestamp}")

        final_message = "\n".join(formatted_messages)

        system_prompt = """
                    Faz um resumo dessas últimas mensagens.
                    Formata com o estilo de md do whatsapp. Vai ser enviado pra lá então precisa ser compativel com a formatação dele.
                    O resumo não deve ser muito longo, passe pelos tópicos mais importantes e discutidos, caso apenas um tema seja discutido pode se extender mais nele.
                 """.strip()

        payload = {
            "model": model.openrouter_id,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": final_message
                }
            ],
        }

        req = await completions(payload)
        conversation_resume = req["choices"][0]["message"]["content"]

        command = await command_repo.insert(
            Command(
                user_id=user_id,
                group_id=group_id,
                command="resume"
            )
        )

        interaction_repo = InteractionRepository(Interaction, db)
        _ = await interaction_repo.create_interaction(
            model_id=model.id,
            user_id=user_id,
            group_id=None,
            command_id=command.id,
            user_prompt=final_message,
            system_behavior=system_prompt,
            response=conversation_resume,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"]
        )

        return conversation_resume