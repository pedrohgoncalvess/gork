from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.core import COMMANDS
from database.models.manager import Model
from database.operations.manager import ModelRepository
from external.evolution import send_message
from api.routes.webhook.evolution.functions import get_resume_conversation, token_consumption


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
