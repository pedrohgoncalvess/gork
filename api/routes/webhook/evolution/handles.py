import re
from datetime import datetime, timedelta
from typing import Optional
from textwrap import dedent
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.models.manager import Model
from database.operations.manager import ModelRepository
from functions import get_resume_conversation, generic_conversation, generate_sticker, remember_generator, generate_image
from functions.tokens import token_consumption
from functions.transcribe_audio import transcribe_audio
from functions.web_search import web_search
from external.evolution import send_message, send_audio, send_sticker, send_image
from services.remember import action_remember
from tts import text_to_speech


COMMANDS = [
    ("@Gork", "Interação genérica. _[Menção necessária apenas quando em grupos]_"),
    ("!help", "Mostra os comandos disponíveis. _[Ignora o restante da mensagem]_"),
    ("!audio", "Envia áudio como forma de resposta. _[Adicione !english para voz em inglês]_"),
    ("!resume", "Faz um resumo das últimas 30 mensagens. _[Ignora o restante da mensagem]_"),
    ("!search", "Faz uma pesquisa por termo na internet e retorna um resumo."),
    ("!model", "Mostra o modelo sendo utilizado."),
    ("!sticker", "Cria um sticker com base em uma imagem e texto fornecido. _[Use | como separador de top/bottom]_"),
    ("!english", ""),
    ("!remember",
     "Cria um lembrete para o dia, hora e tópico solicitado. _[Ex: Lembrete para comentar amanhã as 4 da tarde]_"),
    ("!transcribe", "Transcreve um áudio. _[Ignora o restante da mensagem]_"),
    ("!image", "Gera ou modifica uma imagem mencionada."),
    ("!consumption", "Gera relatório de consumo de grupos e usuários.")
]


async def extract_conversation_text(message_data: dict) -> str:
    caption = message_data.get('imageMessage', {}).get('caption', '')
    conversation = caption if caption else message_data.get("conversation", "")

    if not conversation:
        conversation = (
            message_data.get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("text", "")
        )

    return conversation


async def is_message_too_old(timestamp: int, max_minutes: int = 20) -> bool:
    created_at = datetime.fromtimestamp(timestamp)
    return created_at < (datetime.now() - timedelta(minutes=max_minutes))


def clean_text(text: str) -> str:
    treated_text = text.strip()
    for command, _ in COMMANDS:
        treated_text = treated_text.replace(command, "")

    treated_text = re.compile(r'@\d{6,15}').sub('', treated_text)
    return treated_text.strip()


async def handle_help_command(remote_id: str, message_id: str):
    help_message = (
        "🤖 *COMANDOS DO GORK*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "💬 *INTERAÇÃO*\n"
        "*@Gork* - Interação genérica\n"
        "_Menção necessária apenas em grupos_\n\n"

        "🔍 *BUSCA & INFORMAÇÃO*\n"
        "*!search* - Pesquisa na internet\n"
        "*!model* - Mostra modelos em uso\n"
        "*!consumption* - Relatório de consumo\n\n"

        "🎙️ *ÁUDIO & TRANSCRIÇÃO*\n"
        "*!audio* - Responde em áudio\n"
        "_Adicione !english para voz em inglês_\n"
        "*!transcribe* - Transcreve um áudio\n\n"

        "🖼️ *IMAGENS & STICKERS*\n"
        "*!image* - Gera ou modifica imagem\n"
        "*!sticker* - Cria sticker\n"
        "_Use | como separador top/bottom_\n\n"

        "⏰ *LEMBRETES*\n"
        "*!remember* - Cria lembretes\n"
        "_Ex: Lembrete para amanhã às 16h_\n\n"

        "📝 *UTILIDADES*\n"
        "*!resume* - Resume últimas 30 mensagens\n"
        "*!help* - Mostra esta mensagem\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "💡 *DICA: FALE NATURALMENTE!*\n\n"

        "Você não precisa usar comandos. Apenas converse normalmente:\n\n"

        "• \"me avisa amanhã às 10h\"\n"
        "  → _cria lembrete automaticamente_\n\n"

        "• \"pesquisa sobre Python\"\n"
        "  → _busca na internet_\n\n"

        "• \"cria uma imagem de gato espacial\"\n"
        "  → _gera a imagem_\n\n"

        "• \"resume a conversa\"\n"
        "  → _faz resumo do histórico_\n\n"

        "Os comandos (!) são *opcionais*, mas mais rápidos, precisos e econômicos.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 Contribute: github.com/pedrohgoncalvess/gork"
    )

    await send_message(remote_id, help_message, message_id)


async def handle_model_command(remote_id: str, message_id: str, db: AsyncSession):
    model_repo = ModelRepository(Model, db)
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


async def handle_search_command(
        remote_id: str,
        message_id: str,
        treated_text: str,
        group: bool,
        user_id: int
):
    search = await web_search(treated_text, user_id, remote_id, group)
    await send_message(remote_id, search, message_id)


async def handle_image_command(
        remote_id: str,
        user_id: int,
        treated_text: str,
        body: dict,
        group_id: Optional[int] = None
):
    image_base64, error = await generate_image(user_id, treated_text, body, group_id)
    if error:
        await send_message(remote_id, image_base64)
        return
    await send_image(remote_id, image_base64)
    return


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


async def handle_sticker_command(
        remote_id: str,
        body: dict,
        treated_text: str
):
    webp_base64 = await generate_sticker(body, treated_text)
    await send_sticker(remote_id, webp_base64)


async def handle_transcribe_command(
        remote_id: str,
        message_id: str,
        body: dict,
        user_id: int,
        group_id: Optional[int] = None
):
    transcribed_audio = await transcribe_audio(body, user_id, group_id)
    transcribed_audio = f"_{transcribed_audio.strip()}_"
    await send_message(remote_id, transcribed_audio, message_id)


async def handle_remember_command(
        scheduler: AsyncIOScheduler,
        remote_id: str,
        message_id: str,
        user_id: int,
        treated_text: str,
        group_id: Optional[int] = None
):
    remember, feedback_message = await remember_generator(user_id, treated_text, group_id)
    remember.message = f"*[LEMBRETE]* {remember.message}"
    remember.remember_at = remember.remember_at.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))

    scheduler.add_job(
        action_remember,
        'date',
        run_date=remember.remember_at,
        args=[remember, remote_id],
        id=str(remember.id)
    )
    await send_message(remote_id, feedback_message, message_id)


async def handle_generic_conversation(
        remote_id: str,
        message_id: str,
        user: User,
        treated_text: str,
        group_id: Optional[int] = None,
        audio: bool = False
):

    is_group = True if group_id else False
    response_message = await generic_conversation(group_id, user.name, treated_text, user.id, is_group)

    if audio:
        audio_base64 = await text_to_speech(
            response_message.get("text"),
            language=response_message.get("language")
        )
        await send_audio(remote_id, audio_base64, message_id)
    else:
        response_text = f"{response_message.get('text')}"
        await send_message(remote_id, response_text, message_id)


def has_explicit_command(text: str) -> bool:
    return any(cmd in text.lower() for cmd, _ in COMMANDS if cmd.startswith("!"))

def handle_media(body: dict) -> list[str]:
    event_data = body.get("data")

    message_type = event_data.get("messageType")

    audio_message = True if message_type == "audioMessage" else False
    image_message = True if message_type == "imageMessage" else False

    context_info = event_data.get("contextInfo") if event_data.get("contextInfo") is not None else {}
    image_quote = context_info.get("quotedMessage", {}).get("imageMessage")
    if not image_quote:
        image_quote = (
            event_data.get("message", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo", {})
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("imageMessage")
        )

    audio_quote = context_info.get("quotedMessage", {}).get("audioMessage")
    if not audio_quote:
        audio_quote = (
            event_data.get("message", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("extendedTextMessage", {})
            .get("contextInfo", {})
            .get("quotedMessage", {})
            .get("ephemeralMessage", {})
            .get("message", {})
            .get("audioMessage")
        )
    medias = []
    if audio_quote:
        medias.append("audio_quote")
    if image_quote:
        medias.append("image_quote")
    if image_message:
        medias.append("image_message")
    if audio_message:
        medias.append("audio_message")

    return medias