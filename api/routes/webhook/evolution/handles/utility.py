from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.core import COMMANDS
from database import PgConnection
from database.models.content import Message
from database.models.manager import Model, Command
from database.models.manager.interaction import Interaction
from database.operations.content.message import MessageRepository
from database.operations.manager import ModelRepository
from database.operations.manager.command import CommandRepository
from database.operations.manager.interaction import InteractionRepository
from external import completions
from external.evolution import send_message


# ── Resume ───────────────────────────────────────────────────────────────────

async def get_resume_conversation(user_id: int, contact_id: int = None, group_id: int = None) -> str:

    async with PgConnection() as db:

        model_repo = ModelRepository(db)
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

        message_repo = MessageRepository(db)
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


# ── Token consumption ────────────────────────────────────────────────────────

async def token_consumption(user_id: Optional[int] = None, group_id: Optional[int] = None) -> str:
    async with PgConnection() as db:
        interaction_repo = InteractionRepository(Interaction, db)

        consumption_data = await interaction_repo.get_consumption_by_user(
            group_id=group_id
        )

        if user_id is not None:
            consumption_data = [user for user in consumption_data if user['user_id'] == user_id]

        if not consumption_data:
            if user_id is not None:
                return "📊 *Seu Consumo de Tokens*\n\n❌ Você não possui nenhuma interação registrada nas últimas 24 horas."
            elif group_id:
                return "📊 *Relatório de Consumo de Tokens*\n\n❌ Nenhum dado encontrado para este grupo nas últimas 24 horas."
            else:
                return "📊 *Relatório de Consumo de Tokens*\n\n❌ Nenhum dado encontrado nas últimas 24 horas."

        total_interactions = sum(user['total_interactions'] for user in consumption_data)
        total_input_tokens = sum(user['total_input_tokens'] for user in consumption_data)
        total_output_tokens = sum(user['total_output_tokens'] for user in consumption_data)
        total_tokens = sum(user['total_tokens'] for user in consumption_data)
        total_cost = sum(user['estimated_cost'] for user in consumption_data)

        start_date = datetime.now() - timedelta(days=1)
        period_text = f"📅 Período: {start_date.strftime('%d/%m/%Y %H:%M')} até agora"

        if user_id is not None and len(consumption_data) == 1:
            user = consumption_data[0]

            message_parts = [
                "📊 *SEU CONSUMO DE TOKENS*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                period_text,
                "",
                "📈 *RESUMO*",
                f"💬 Interações: {user['total_interactions']:,}",
                f"🔢 Tokens Totais: {user['total_tokens']:,}",
                f"  ├─ 📥 Input: {user['total_input_tokens']:,}",
                f"  └─ 📤 Output: {user['total_output_tokens']:,}",
                f"💰 Custo Estimado: ${user['estimated_cost']:.6f} USD",
                ""
            ]

            if user['models_used']:
                message_parts.extend([
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                    "🤖 *MODELOS UTILIZADOS:*"
                ])

                for model in user['models_used']:
                    message_parts.extend([
                        "",
                        f"• *{model['model_name']}*",
                        f"  ├─ Interações: {model['interaction_count']:,}",
                        f"  ├─ Tokens: {model['total_tokens']:,}",
                        f"  │   ├─ Input: {model['input_tokens']:,}",
                        f"  │   └─ Output: {model['output_tokens']:,}",
                        f"  └─ Custo: ${model['estimated_cost']:.6f}"
                    ])

            message_parts.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "_💡 Relatório gerado automaticamente_"
            ])

        else:
            message_parts = [
                "📊 *RELATÓRIO DE CONSUMO DE TOKENS*",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                period_text
            ]

            message_parts.extend([
                "",
                "📈 *RESUMO GERAL*",
                f"💬 Total de Interações: {total_interactions:,}",
                f"🔢 Total de Tokens: {total_tokens:,}",
                f"  ├─ 📥 Input: {total_input_tokens:,}",
                f"  └─ 📤 Output: {total_output_tokens:,}",
                f"💰 Custo Estimado: ${total_cost:.6f} USD",
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "",
                f"👥 *TOP {len(consumption_data)} USUÁRIOS POR CUSTO:*"
            ])

            for idx, user in enumerate(consumption_data[:10], 1):
                percentage = (user['estimated_cost'] / total_cost * 100) if total_cost > 0 else 0

                message_parts.extend([
                    "",
                    f"*{idx}. {user['user_name']}*",
                    f"├─ 💰 ${user['estimated_cost']:.6f} ({percentage:.1f}%)",
                    f"├─ 💬 {user['total_interactions']:,} interações",
                    f"├─ 🔢 {user['total_tokens']:,} tokens",
                    f"└─ 🤖 {len(user['models_used'])} modelo(s)"
                ])

            if len(consumption_data) > 10:
                message_parts.append(f"\n_... e mais {len(consumption_data) - 10} usuário(s)_")

            message_parts.extend([
                "",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "_💡 Relatório gerado automaticamente_"
            ])

        return "\n".join(message_parts)


# ── Handles ──────────────────────────────────────────────────────────────────

async def handle_help_command(remote_id: str, message_id: str):
    category_info = {
        "interaction": ("💬 *INTERAÇÃO*", []),
        "search": ("🔍 *BUSCA & INFORMAÇÃO*", []),
        "audio": ("🎙️ *ÁUDIO & TRANSCRIÇÃO*", []),
        "image": ("🖼️ *IMAGENS & STICKERS*", []),
        "reminder": ("⏰ *LEMBRETES*", []),
        "utility": ("📝 *UTILIDADES*", []),
        "media": ("📹 *MÍDIA*", []),
    }

    for cmd, desc, category, params in COMMANDS:
        if category != "hidden" and desc:
            category_info[category][1].append((cmd, desc, params))

    help_parts = [
        "🤖 *COMANDOS DO GORK*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ""
    ]

    for category, (title, commands) in category_info.items():
        if commands:
            help_parts.append(title)
            for cmd, desc, params in commands:
                help_parts.append(f"*{cmd}* - {desc}")

                if params:
                    help_parts.append("  _Parâmetros:_")
                    for param_name, param_desc, param_options in params:
                        help_parts.append(f"  • *{param_name}* - {param_desc}")
                        if param_options:
                            options_str = "\n".join([f"        - _{opt}_ ({desc})" for opt, desc in param_options])
                            help_parts.append(f"    Opções:\n {options_str}")

            help_parts.append("")

    help_parts.extend([
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "💡 *DICA: FALE NATURALMENTE!*",
        "",
        "Você não precisa usar comandos. Apenas converse normalmente:",
        "",
        "• \"me avisa amanhã às 10h\"",
        "  → _cria lembrete automaticamente_",
        "",
        "• \"pesquisa sobre Python\"",
        "  → _busca na internet_",
        "",
        "• \"cria uma imagem de gato espacial\"",
        "  → _gera a imagem_",
        "",
        "• \"resume a conversa\"",
        "  → _faz resumo do histórico_",
        "",
        "Os comandos (!) são *opcionais*, mas mais rápidos, precisos e econômicos.",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "🔗 Contribute: github.com/pedrohgoncalvess/gork"
    ])

    help_message = "\n".join(help_parts)
    await send_message(remote_id, help_message, message_id)


async def handle_model_command(remote_id: str, message_id: str, db: AsyncSession):
    model_repo = ModelRepository(db)
    model = await model_repo.get_default_model()
    audio_model = await model_repo.get_default_audio_model()
    image_model = await model_repo.get_default_image_model()

    formatted_text = (
        "🤖 *MODELOS EM USO*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💬 *Texto*\n"
        f"└─ _{model.name}_\n\n"
        f"🎙️ *Áudio*\n"
        f"└─ _{audio_model.name}_\n\n"
        f"🖼️ *Imagem*\n"
        f"└─ _{image_model.name}_\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "_💡 Modelos padrão do sistema_"
    )
    await send_message(remote_id, formatted_text, message_id)


async def handle_resume_command(
        remote_id: str,
        message_id: str,
        user_id: int,
        group_id: Optional[int] = None
):
    resume = await get_resume_conversation(user_id, group_id=group_id)
    await send_message(remote_id, resume, message_id)


async def handle_consumption_command(
        remote_id: str,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None
):
    if user_id:
        analytics = await token_consumption(user_id=user_id)
    else:
        analytics = await token_consumption(group_id=group_id)

    await send_message(remote_id, analytics)
    return
