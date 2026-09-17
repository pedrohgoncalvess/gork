import asyncio
import base64
import binascii
import json
import re
from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.core import clean_text
from database import PgConnection
from database.models.content import Message
from database.operations.content import MediaRepository, MessageRepository
from database.models.manager import Command, Interaction
from database.operations.base import UserRepository
from database.operations.manager import (
    AgentRepository,
    CommandRepository,
    InteractionRepository,
    ModelConversationRepository,
)
from external import (
    OpenRouterVideoError,
    download_video,
    submit_video,
    upload_temporary_file,
    wait_for_video,
)
from external.evolution import download_media, send_message, send_video
from log import logger
from s3 import S3Client
from services import get_mentions_from_content, parse_params
from utils import INSTANCE_NUMBER


DEFAULT_DURATION = 5
MAX_DURATION = 10
MAX_VIDEO_BYTES = 100 * 1024 * 1024
MAX_REFERENCE_BYTES = 95 * 1024 * 1024
QUALITY_ORDER = ("480p", "720p", "1080p", "2K", "4K")
_VIDEO_TASKS: set[asyncio.Task] = set()


@dataclass(frozen=True)
class VideoOptions:
    duration: int
    resolution: str
    aspect_ratio: str
    generate_audio: bool


class VideoRequestError(ValueError):
    pass


def video_submit_error_message(error: Exception) -> str:
    if not isinstance(error, OpenRouterVideoError):
        return "Não consegui iniciar a geração do vídeo. Tente novamente."

    code = str(error.provider_code or "").lower()
    message = error.provider_message.lower()
    if "privacyinformation" in code or "real person" in message:
        return (
            "O modelo recusou a imagem porque detectou uma pessoa real ou "
            "informações de privacidade. Tente sem a foto/menção, use uma "
            "referência sem rosto real ou escolha outro modelo de vídeo."
        )
    if any(term in code or term in message for term in (
        "sensitivecontent", "content_policy", "content policy", "safety",
    )):
        return (
            "O modelo recusou o pedido ou uma das referências pelas regras de "
            "segurança. Remova o conteúdo sensível e tente novamente."
        )
    if error.status_code == 402:
        return "A OpenRouter recusou a geração por saldo ou limite de créditos insuficiente."
    if error.status_code == 429:
        return "O serviço de vídeo está com muitas solicitações. Aguarde um pouco e tente novamente."
    if error.status_code == 404:
        return "O modelo de vídeo configurado não está disponível na OpenRouter."
    if any(term in code or term in message for term in (
        "invalidimage", "imagefetch", "download", "reference",
    )):
        return (
            "O provedor não conseguiu processar uma das imagens ou vídeos de "
            "referência. Tente outra mídia."
        )
    if error.status_code >= 500:
        return "O provedor de vídeo está indisponível no momento. Tente novamente mais tarde."
    return (
        "A OpenRouter recusou os parâmetros ou o conteúdo desse vídeo. "
        "Revise o pedido e tente novamente."
    )


def _enabled(value: object) -> bool:
    return str(value).strip().lower() in {"true", "t", "1", "yes", "y"}


def normalize_quality(value: object) -> str:
    normalized = str(value).strip().lower().replace("p", "")
    aliases = {
        "480": "480p",
        "720": "720p",
        "1080": "1080p",
        "2k": "2K",
        "4k": "4K",
    }
    quality = aliases.get(normalized)
    if quality is None:
        raise VideoRequestError("Qualidade inválida. Use 480, 720, 1080, 2k ou 4k.")
    return quality


def resolve_video_options(params: dict, capabilities: dict) -> VideoOptions:
    try:
        duration = int(params.get("duration", DEFAULT_DURATION))
    except (TypeError, ValueError):
        raise VideoRequestError("A duração deve ser um número inteiro entre 1 e 10.")
    if not 1 <= duration <= MAX_DURATION:
        raise VideoRequestError("A duração deve ficar entre 1 e 10 segundos.")

    supported_durations = {
        int(value)
        for value in capabilities.get("supported_durations", [])
        if str(value).isdigit()
    }
    if not supported_durations:
        raise VideoRequestError("Ainda não tenho as durações suportadas pelo modelo de vídeo.")
    if duration not in supported_durations:
        available = ", ".join(map(str, sorted(d for d in supported_durations if d <= MAX_DURATION)))
        raise VideoRequestError(
            f"Esse modelo não suporta {duration}s. Durações disponíveis até 10s: {available or 'nenhuma'}."
        )

    supported_resolutions = {
        str(value) for value in capabilities.get("supported_resolutions", [])
    }
    if not supported_resolutions:
        raise VideoRequestError("Ainda não tenho as qualidades suportadas pelo modelo de vídeo.")

    requested_quality = params.get("quality")
    if requested_quality is not None:
        resolution = normalize_quality(requested_quality)
        if resolution not in supported_resolutions:
            available = ", ".join(
                quality for quality in QUALITY_ORDER if quality in supported_resolutions
            )
            raise VideoRequestError(
                f"Esse modelo não suporta {resolution}. Qualidades disponíveis: {available or 'não informadas'}."
            )
    else:
        resolution = next(
            (quality for quality in QUALITY_ORDER if quality in supported_resolutions),
            None,
        )
        if resolution is None:
            raise VideoRequestError("O modelo não informou uma qualidade de vídeo reconhecida.")

    generate_audio = _enabled(params.get("audio", False))
    if generate_audio and not capabilities.get("generate_audio", False):
        raise VideoRequestError("O modelo de vídeo configurado não oferece geração de áudio.")

    supported_aspect_ratios = [
        str(value) for value in capabilities.get("supported_aspect_ratios", [])
    ]
    if not supported_aspect_ratios:
        raise VideoRequestError("O modelo não informou proporções de vídeo suportadas.")
    aspect_ratio = (
        "16:9" if "16:9" in supported_aspect_ratios else supported_aspect_ratios[0]
    )

    return VideoOptions(duration, resolution, aspect_ratio, generate_audio)


def _replace_user_references(text: str, users: list, me_user=None) -> str:
    for user in users:
        replacement = user.name or "Usuário"
        identifiers = filter(None, (user.phone_number, user.src_id))
        for identifier in identifiers:
            text = text.replace(f"@{identifier}@s.whatsapp.net", replacement)
            text = text.replace(f"{identifier}@lid", replacement)
            text = text.replace(f"@{identifier}", replacement)
    return re.sub(
        r"(?<!\w)@me\b",
        (me_user.name or "Usuário") if me_user else "Usuário",
        text,
        flags=re.I,
    )


async def _reference_images(users: list) -> list[dict]:
    missing = [user.name or "Usuário" for user in users if not user.profile_pic_path]
    if missing:
        raise VideoRequestError(
            "Não encontrei foto de perfil para: " + ", ".join(missing) + "."
        )
    if not users:
        return []

    client = S3Client()
    await client.connect()
    references = []
    for index, user in enumerate(users, start=1):
        image_base64 = await client.get_image_base64("whatsapp", user.profile_pic_path)
        if not image_base64:
            raise VideoRequestError(f"Não consegui carregar a foto de {user.name or 'Usuário'}.")
        image_bytes = base64.b64decode(image_base64)
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image_format = str(image.format or "JPEG").upper()
        except Exception as error:
            raise VideoRequestError(
                f"A foto de {user.name or 'Usuário'} não é uma imagem válida."
            ) from error
        extension, mime_type = {
            "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp"),
            "GIF": ("gif", "image/gif"),
        }.get(image_format, ("jpg", "image/jpeg"))
        image_url = await upload_temporary_file(
            image_bytes,
            f"video-reference-{index}.{extension}",
            mime_type,
        )
        references.append({
            "type": "image_url",
            "image_url": {"url": image_url},
        })
    return references


def _quoted_media_kind(media) -> str | None:
    media_type = str(media.type or "").lower()
    filename = str(media.name or "").lower()
    if media_type in {"image", "jpg", "jpeg", "png", "webp"} or filename.endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    ):
        return "image"
    if media_type in {"video", "mp4", "mov", "webm"} or filename.endswith(
        (".mp4", ".mov", ".webm")
    ):
        return "video"
    return None


async def _quoted_media_reference(
    db_message: Message,
    db: AsyncSession,
) -> tuple[dict, str] | None:
    if not db_message.quoted_message_id:
        return None

    quoted_message = await MessageRepository(db).find_by_id(db_message.quoted_message_id)
    if not quoted_message or not quoted_message.media_id:
        return None
    media = await MediaRepository(db).find_by_id(quoted_message.media_id)
    if not media:
        return None

    kind = _quoted_media_kind(media)
    if not kind:
        return None

    media_base64 = None
    try:
        client = S3Client()
        await client.connect()
        media_base64 = await client.get_image_base64(media.bucket, media.path)
    except Exception:
        # Older messages may still be available through Evolution even when the
        # local object was not persisted or has moved.
        downloaded = await download_media(quoted_message.message_id)
        if downloaded:
            media_base64 = downloaded[0]
    if not media_base64:
        raise VideoRequestError("Não consegui carregar a mídia citada.")

    try:
        media_bytes = base64.b64decode(media_base64, validate=True)
    except (binascii.Error, ValueError) as error:
        raise VideoRequestError("A mídia citada está corrompida.") from error
    if not media_bytes or len(media_bytes) > MAX_REFERENCE_BYTES:
        raise VideoRequestError("A mídia citada está vazia ou ultrapassa 95 MB.")

    if kind == "image":
        try:
            with Image.open(BytesIO(media_bytes)) as image:
                image_format = str(image.format or "JPEG").upper()
        except Exception as error:
            raise VideoRequestError("A imagem citada está corrompida.") from error
        extension, mime_type = {
            "PNG": ("png", "image/png"),
            "WEBP": ("webp", "image/webp"),
        }.get(image_format, ("jpg", "image/jpeg"))
        reference_type = "image_url"
    else:
        filename = str(media.name or "").lower()
        if filename.endswith(".webm"):
            extension, mime_type = "webm", "video/webm"
        elif filename.endswith(".mov"):
            extension, mime_type = "mov", "video/quicktime"
        else:
            extension, mime_type = "mp4", "video/mp4"
        reference_type = "video_url"

    media_url = await upload_temporary_file(
        media_bytes,
        f"quoted-video-reference.{extension}",
        mime_type,
    )
    return (
        {
            "type": reference_type,
            reference_type: {"url": media_url},
        },
        kind,
    )


async def handle_video_command(
    remote_id: str,
    user_id: int,
    db_message: Message,
    db: AsyncSession,
    action_params: dict | None = None,
) -> None:
    params = parse_params(db_message.content or "")
    params.update(action_params or {})

    agent_repo = AgentRepository(db)
    model_conversation_repo = ModelConversationRepository(db)
    video_agent = await agent_repo.find_by_name("video-generation")
    if not video_agent:
        await send_message(remote_id, "O agente de vídeo ainda não está configurado.", db_message.message_id)
        return
    model = await model_conversation_repo.resolve_agent_model(
        video_agent,
        user_id=user_id,
        group_id=db_message.group_id,
    )
    if not model:
        await send_message(remote_id, "O modelo de vídeo ainda não está configurado.", db_message.message_id)
        return

    capabilities = (model.metadata_ or {}).get("video", {})
    try:
        options = resolve_video_options(params, capabilities)
        mentions = await get_mentions_from_content(db_message, db)
        me_user = await UserRepository(db).find_by_id(user_id) if re.search(
            r"(?<!\w)@me\b", db_message.content or "", re.I
        ) else None
        gork_user = await UserRepository(db).find_by_phone_or_id(INSTANCE_NUMBER)
        if gork_user:
            mentions = [user for user in mentions if user.id != gork_user.id]
        references = await _reference_images(mentions)
        quoted_reference = await _quoted_media_reference(db_message, db)
        if quoted_reference:
            references.append(quoted_reference[0])
    except VideoRequestError as error:
        await send_message(remote_id, str(error), db_message.message_id)
        return
    except Exception as error:
        await logger.error("VideoGeneration", "ReferenceLoadFailed", str(error))
        await send_message(
            remote_id,
            "Não consegui carregar as mídias de referência. Tente novamente.",
            db_message.message_id,
        )
        return

    raw_prompt = str(params.get("prompt") or db_message.content or "")
    user_prompt = clean_text(
        _replace_user_references(raw_prompt, mentions, me_user),
        remove_mentions=False,
    )
    if not user_prompt:
        await send_message(remote_id, "Descreva o vídeo que você quer gerar.", db_message.message_id)
        return

    manifest_entries = [
        f"Reference [{index}] identifies {user.name or 'Usuário'}"
        for index, user in enumerate(mentions, start=1)
    ]
    if quoted_reference:
        quoted_index = len(manifest_entries) + 1
        manifest_entries.append(
            f"Reference [{quoted_index}] is the {quoted_reference[1]} quoted by the user"
        )
    manifest = ", ".join(manifest_entries) or "No references were provided."
    payload = {
        "model": model.openrouter_id,
        "prompt": (
            f"{video_agent.prompt.strip()}\n\n"
            f"REFERENCE MANIFEST:\n{manifest}\n\n"
            f"USER REQUEST:\n{user_prompt}"
        ),
        "duration": options.duration,
        "resolution": options.resolution,
        "aspect_ratio": options.aspect_ratio,
        "generate_audio": options.generate_audio,
    }
    if references:
        payload["input_references"] = references

    try:
        command = await CommandRepository(Command, db).create_command(
            "video", user_id, db_message.group_id
        )
        job = await submit_video(payload)
    except Exception as error:
        await logger.error("VideoGeneration", "SubmitFailed", str(error))
        await send_message(
            remote_id,
            video_submit_error_message(error),
            db_message.message_id,
        )
        return

    await send_message(
        remote_id,
        f"🎬 Gerando vídeo de {options.duration}s em {options.resolution}. Eu envio assim que ficar pronto.",
        db_message.message_id,
    )
    task = asyncio.create_task(_finish_video(
        remote_id=remote_id,
        quoted_message_id=db_message.message_id,
        user_id=user_id,
        group_id=db_message.group_id,
        agent_id=video_agent.id,
        model_id=model.id,
        command_id=command.id,
        user_prompt=user_prompt,
        job=job,
    ))
    _VIDEO_TASKS.add(task)
    task.add_done_callback(_VIDEO_TASKS.discard)


async def _finish_video(**context) -> None:
    remote_id = context["remote_id"]
    try:
        completed = await wait_for_video(context["job"])
        job_id = str(completed.get("id") or context["job"].get("id"))
        usage = completed.get("usage") or {}
        await _record_video_interaction(context, completed, job_id, usage)

        video_bytes = await download_video(job_id)
        if not video_bytes or len(video_bytes) > MAX_VIDEO_BYTES:
            raise ValueError("Generated video is empty or exceeds 100 MB")
        await send_video(
            remote_id,
            base64.b64encode(video_bytes).decode("ascii"),
            context["quoted_message_id"],
        )
    except Exception as error:
        await logger.error("VideoGeneration", "CompletionFailed", str(error))
        await send_message(remote_id, "Não consegui concluir a geração do vídeo. Tente novamente.")


async def _record_video_interaction(
    context: dict,
    completed: dict,
    job_id: str,
    usage: dict,
) -> None:
    async with PgConnection() as db:
        await InteractionRepository(Interaction, db).create_interaction(
            model_id=context["model_id"],
            user_id=context["user_id"],
            group_id=context["group_id"],
            agent_id=context["agent_id"],
            command_id=context["command_id"],
            user_prompt=context["user_prompt"],
            response=json.dumps({
                "id": job_id,
                "status": completed.get("status"),
                "usage": usage,
            }),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            actual_cost=usage.get("cost"),
        )
