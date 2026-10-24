import json
from datetime import datetime, timedelta

from database import PgConnection
from database.models.manager import Command, Interaction
from database.operations.content import MessageRepository
from database.operations.manager import AgentRepository, CommandRepository, InteractionRepository, ModelConversationRepository, ModelRepository
from external import completions

async def get_resume_conversation(user_id: int, contact_id: int = None, group_id: int = None) -> str:

    async with PgConnection() as db:

        model_repo = ModelRepository(db)
        command_repo = CommandRepository(Command, db)
        agent_repo = AgentRepository(db)
        model_conv_repo = ModelConversationRepository(db)

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

        now_time = datetime.now()
        recent_commands = [
            cmd for cmd in commands
            if cmd.inserted_at and (
                now_time - (cmd.inserted_at.replace(tzinfo=None) if cmd.inserted_at.tzinfo else cmd.inserted_at)
            ) <= timedelta(hours=2)
        ]

        if len(recent_commands) > 0:
            most_recent = max(recent_commands, key=lambda cmd: cmd.inserted_at)
            inserted_naive = most_recent.inserted_at.replace(tzinfo=None) if most_recent.inserted_at.tzinfo else most_recent.inserted_at
            time_diff = now_time - inserted_naive

            hours = int(time_diff.total_seconds() // 3600)
            minutes = int((time_diff.total_seconds() % 3600) // 60)

            time_str = f"{hours:02d}:{minutes:02d}"

            return f"Executei esse comando tem {time_str}hr"

        resume_agent = await agent_repo.find_by_name("resume")
        model = None
        if resume_agent:
            model = await model_conv_repo.resolve_agent_model(
                resume_agent,
                user_id=user_id,
                group_id=group_id
            )

        if not model:
            model = await model_repo.get_default_model()

        message_repo = MessageRepository(db)
        if group_id:
            messages = await message_repo.find_by_group(group_id, 100)
        else:
            messages = await message_repo.find_by_sender(user_id, 100)

        messages = sorted(messages, key=lambda m: (m.created_at or datetime.min, m.id or 0))

        formatted_messages = []

        for msg in messages:
            sender_name = "Usuário Desconhecido"
            if msg.sender:
                sender_name = msg.sender.name or msg.sender.phone_number or msg.sender.src_id or "Usuário"
            content = msg.content or ""

            if msg.created_at:
                msg_date = msg.created_at.date()
                today = datetime.now().date()

                if msg_date != today:
                    timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
                else:
                    timestamp = msg.created_at.strftime('%H:%M')
            else:
                timestamp = ""

            formatted_messages.append(f"{sender_name}: {content} - {timestamp}")

        final_message = "\n".join(formatted_messages)

        if resume_agent and resume_agent.prompt:
            system_prompt = resume_agent.prompt
        else:
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

        if resume_agent and resume_agent.response_format:
            try:
                payload["response_format"] = json.loads(resume_agent.response_format)
            except Exception:
                pass

        req = await completions(payload)
        conversation_resume = req["choices"][0]["message"]["content"]
        if resume_agent and resume_agent.response_format:
            try:
                parsed_json = json.loads(conversation_resume)
                if isinstance(parsed_json, dict) and "summary" in parsed_json:
                    conversation_resume = parsed_json["summary"]
            except Exception:
                pass

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
            group_id=group_id,
            command_id=command.id,
            user_prompt=final_message,
            system_behavior=system_prompt,
            response=conversation_resume,
            input_tokens=req.get("usage", {}).get("prompt_tokens", 0),
            output_tokens=req.get("usage", {}).get("completion_tokens", 0)
        )

        return conversation_resume
