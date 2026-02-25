import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.models.content import Message
from database.models.manager import Model
from database.operations.content import MessageRepository
from database.operations.manager import ModelRepository
from api.routes.webhook.evolution.functions import (
    get_resume_conversation, generic_conversation,
    static, animated, remember_generator,
    generate_image, list_images, search_images,
    token_consumption, transcribe_audio, web_search, get_pictures,
    download_twitter_media, extract_twitter_url
)

import base64
from log import logger
from external.evolution import (
    send_message, send_audio, send_sticker,
    send_animated_sticker, send_image, download_media, send_video
)
from services import describe_image, parse_params, action_remember
from tts import text_to_speech


COMMANDS = [
    ("@Gork", "Interação genérica. _[Menção necessária apenas quando em grupos]_", "interaction", []),
    ("!help", "Mostra os comandos disponíveis. _[Ignora o restante da mensagem]_", "utility", []),
    ("!audio", "Envia áudio como forma de resposta. _[Adicione !english para voz em inglês]_", "audio", []),
    ("!resume", "Faz um resumo das últimas 30 mensagens. _[Ignora o restante da mensagem]_", "utility", []),
    ("!search", "Faz uma pesquisa por termo na internet e retorna um resumo.", "search", []),
    ("!model", "Mostra o modelo sendo utilizado.", "search", []),
    ("!picture", "Envia a foto dos usuários mencionados", "image", []),
    (
        "!sticker",
        "Cria um sticker com base em uma imagem e texto fornecido. _[Use | como separador de top/bottom]_ \n_(Obs: Mensagens quotadas com !sticker será criado um sticker da mensagem com a foto de perfil de quem enviou)_",
        "image",
        [
            (":no-background", "Remove fundo da imagem.", [("t", "Verdadeiro"),]),
            (":random", "Usa uma imagem aleatória", [("t", "Verdadeiro"),]),
            (":effect", "Adiciona um efeito. *Apenas figurinhas animadas*", [
                ("explosion", "Efeito de explosão"),
                ("breathing", "Efeito de respiração (infla e desinfla)"),
                ("rotation", "Efeito de rotação (360 graus)"),
                ("bulge", "Efeito de balão/infla"),
                ("pinch", "Efeito de pinça/implode"),
                ("swirl", "Efeito de redemoinho"),
                ("wave", "Efeito de ondas"),
                ("fisheye", "Efeito olho de peixe"),
            ]),
        ]
    ),
    ("!english", "", "hidden", []),
    ("!remember", "Cria um lembrete para o dia, hora e tópico solicitado. _[Ex: Lembrete para comentar amanhã as 4 da tarde]_", "reminder", []),
    ("!transcribe", "Transcreve um áudio. _[Ignora o restante da mensagem]_", "audio", []),
    ("!image", "Gera ou modifica uma imagem mencionada. _[Mencione alguém para adicionar a foto de perfil ao contexto de criação. Adicione @me na mensagem e sua foto vai ser mencionada no contexto.]_", "image", []),
    ("!consumption", "Gera relatório de consumo de grupos e usuários.", "search", []),
    ("!describe", "Descreve uma imagem.", "image", []),
    ("!gallery", "Lista as imagens enviadas. _[Filtros podem ser feitos com termos ou datas]_", "image", []),
    ("!favorite", "Favorita uma mensagem.", "utility", []),
    ("!list", "", "hidden", []),
    ("!remove", "", "hidden", []),
    ("!twitter", "Baixa vídeos ou imagens de links do X/Twitter e envia. _[Ex: !twitter https://x.com/usuario/status/12345]_", "media", []),
]


async def is_message_too_old(timestamp: int, max_minutes: int = 20) -> bool:
    created_at = datetime.fromtimestamp(timestamp)
    return created_at < (datetime.now() - timedelta(minutes=max_minutes))


def clean_text(text: str, remove_mentions: bool = True) -> str:
    treated_text = text.strip()
    for command, _, _, _ in COMMANDS:
        treated_text = treated_text.replace(command, "")

    if remove_mentions:
        treated_text = re.compile(r'@\d{6,15}').sub('', treated_text)
    treated_text = re.compile(r'\s*:[a-zA-Z-]+=\S+').sub('', treated_text)
    return treated_text.strip()


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
        raw_text: str,
        body: dict,
        group_id: Optional[int] = None
):
    treated_text = clean_text(raw_text, False)
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
        treated_text: str,
        message: str,
        db: AsyncSession,
        message_context: dict
):

    medias = message_context.keys()
    params = parse_params(message)
    if "video_message" in medias or "video_quote" in medias or "sticker_quote" in medias:
        effect = params.get("effect")
        if "video_quote" in medias:
            message_id = message_context.get("video_quote")
        elif "video_message" in medias:
            message_id = message_context.get("video_message")
        else:
            message_id = message_context.get("sticker_quote")
        gif_url = await animated(message_id, treated_text, effect)
        await send_animated_sticker(remote_id, gif_url)
    else:
        is_random = True if params.get("random", "f") == "t" else False
        remove_background = True if params.get("no-background", "f") == "t" else False
        webp_base64 = await static(
            body, treated_text, db,
            message_context, is_random, remove_background
        )
        await send_sticker(remote_id, webp_base64)


async def handle_describe_image_command(
        remote_id: str,
        user_id: int,
        treated_text: str,
        medias: dict[str, str],
        group_id: Optional[int] = None
):
    if "image_message" in medias.keys():
        image_base64, _ = await download_media(medias["image_message"])
    else:
        image_base64, _ = await download_media(medias["image_quote"])

    resume = await describe_image(user_id, treated_text, image_base64, group_id)
    await send_message(remote_id, resume)
    return


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
        context: dict[str, str],
        group_id: Optional[int] = None,
        audio: bool = False
):

    is_group = True if group_id else False
    response_message = await generic_conversation(group_id, user.name, treated_text, user.id, context, is_group)

    if audio:
        audio_base64 = await text_to_speech(
            response_message.get("text"),
            language=response_message.get("language")
        )
        await send_audio(remote_id, audio_base64, message_id)
        return
    else:
        response_text = f"{response_message.get('text')}"
        await send_message(remote_id, response_text, message_id)
        return


def has_explicit_command(text: str) -> bool:
    return any(cmd in text.lower() for cmd, _, _, _ in COMMANDS if cmd.startswith("!"))


async def handle_list_images_command(
        remote_id: str, treated_text: Optional[str],
        db: AsyncSession, user_id: Optional[int] = None,
        group_id: Optional[int] = None
):
    if treated_text:
        message = await search_images(treated_text, user_id=user_id, group_id=group_id, db=db)
    else:
        message = await list_images(
            user_id=user_id if not group_id else None,
            group_id=group_id,
            db=db
        )
    await send_message(remote_id, message)
    return


async def handle_favorite_message(
    remote_id: str, context: dict[str, any],
    db: AsyncSession
):
    message_id = context.get("quoted_message")
    message_repo = MessageRepository(Message, db)
    message = await message_repo.set_is_favorite(message_id)

    feedback_message = "✅ Mensagem favoritada." if message else "❌ Houve um erro ao favoritar a mensagem."

    await send_message(remote_id, feedback_message)

    return


async def handle_picture_command(
    remote_id: str,
    context: dict[str, any],
    db: AsyncSession,
):
    message_id = context.get("quoted_message")
    mentions = context.get("mentions")

    if len(mentions) == 0:
        await send_message(remote_id, "Ninguem foi mencionado.", message_id)

    pictures_for_send = await get_pictures(context, db)

    for type_, picture in pictures_for_send:
        if type_:
            await send_image(remote_id, picture)
        else:
            await send_message(remote_id, picture, message_id)

    return


async def handle_list_favorites_message(
        remote_id: str, db: AsyncSession,
        message_id: str, user_id: Optional[int] = None,
        group_id: Optional[int] = None, last_days: Optional[int] = None,
        user_name: Optional[str] = None
):
    message_repo = MessageRepository(Message, db)
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
    message_repo = MessageRepository(Message, db)
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


async def handle_twitter_command(
        remote_id: str,
        conversation: str,
        message_id: str
):
    """
    Handler para o comando !twitter. Baixa mídia (vídeo ou imagem) de um link do X/Twitter e envia.

    Processa URLs do Twitter/X, baixa a mídia (vídeo ou imagem) e envia via WhatsApp.
    Detecta automaticamente o tipo de mídia e envia usando o método apropriado.

    Args:
        remote_id: ID do destinatário (telefone ou grupo)
        conversation: Texto completo da mensagem (contém o link do Twitter)
        message_id: ID da mensagem para resposta

    Raises:
        Nenhuma exceção é propagada; erros são tratados e retornados como mensagem ao usuário

    Examples:
        >>> # Mensagem do usuário:
        >>> # "!twitter https://x.com/usuario/status/12345"
        >>> await handle_twitter_command("5511999999999@s.whatsapp.net", "!twitter https://x.com/usuario/status/12345", "msg_123")
    """
    # Extrai o URL do Twitter/X
    twitter_url = extract_twitter_url(conversation)

    if not twitter_url:
        await logger.warning(
            "TwitterCommand",
            "URL não encontrada",
            {"conversation": conversation}
        )
        await send_message(
            remote_id,
            "❌ Põe um link válido do Twitter/X, animal.\n\n"
            "Exemplo de uso:\n"
            "`!twitter https://x.com/usuario/status/12345`",
            message_id
        )
        return

    await logger.info(
        "TwitterCommand",
        "Iniciando download",
        {"url": twitter_url, "remote_id": remote_id}
    )

    # Envia mensagem de processamento
    await send_message(remote_id, "⏳ Calma lá, chifrudo..", message_id)

    # Baixa a mídia (vídeo ou imagem)
    result = await download_twitter_media(twitter_url)

    if not result.is_success:
        await logger.error(
            "TwitterCommand",
            "Falha no download",
            {
                "url": twitter_url,
                "error": result.error,
                "media_type": result.media_type,
            }
        )
        await send_message(remote_id, f"❌ {result.error}", message_id)
        return

    # Valida dados
    if not result.media_bytes or not result.media_type:
        await logger.error(
            "TwitterCommand",
            "Dados inválidos",
            {"url": twitter_url, "has_bytes": bool(result.media_bytes), "media_type": result.media_type}
        )
        await send_message(
            remote_id,
            "❌ Deu ruim, cria. Tente daqui um tempo",
            message_id
        )
        return

    # Converte para base64 para envio
    try:
        media_base64 = base64.b64encode(result.media_bytes).decode('utf-8')
    except Exception as e:
        await logger.error("TwitterCommand", "Erro ao codificar base64", str(e))
        await send_message(
            remote_id,
            "❌ Esse vídeo ta quebrado, favor parar de gastar tokens nele.",
            message_id
        )
        return

    # Envia a mídia via WhatsApp de acordo com o tipo
    try:
        if result.media_type == "video":
            await send_video(remote_id, media_base64, message_id)
            await logger.info(
                "TwitterCommand",
                "Vídeo enviado",
                {"url": twitter_url, "size": len(result.media_bytes)}
            )
            await send_message(remote_id, "✅ Vídeo enviado com sucesso!", message_id)
        else:
            await send_image(remote_id, media_base64)
            await logger.info(
                "TwitterCommand",
                "Imagem enviada",
                {"url": twitter_url, "size": len(result.media_bytes)}
            )
            await send_message(remote_id, "✅ Imagem enviada com sucesso!", message_id)
    except Exception as e:
        await logger.error("TwitterCommand", "Erro ao enviar mídia", str(e))
        await send_message(
            remote_id,
            f"❌ Erro ao enviar a mídia: {str(e)}",
            message_id
        )
        return


