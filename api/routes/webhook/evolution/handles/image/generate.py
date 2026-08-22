import base64
import binascii
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import httpx
from PIL import Image

from database import PgConnection
from database.models.base import User
from database.models.manager import Command, Interaction
from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from database.operations.manager import (
    AgentRepository,
    CommandRepository,
    InteractionRepository,
    ModelConversationRepository,
)
from external import generate_images
from external.evolution import download_media
from log import logger
from s3 import S3Client
from services import get_mentions_from_content
from services.message_context import _has_me_mention
from utils import INSTANCE_NUMBER


MAX_GENERATED_IMAGE_BYTES = 20 * 1024 * 1024
IMAGE_FORMAT_MIME_TYPES = {
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
}


@dataclass(frozen=True)
class ImageGenerationResult:
    success: bool
    image_base64: str | None = None
    error_code: str | None = None
    user_message: str | None = None


@dataclass(frozen=True)
class ImageInputReference:
    image_base64: str
    mime_type: str
    role: str
    label: str

    def payload_item(self) -> dict:
        return {
            "type": "image_url",
            "image_url": {
                "url": f"data:{self.mime_type};base64,{self.image_base64}",
            },
        }


class ImageGenerationError(Exception):
    def __init__(self, code: str, user_message: str, detail: str = ""):
        super().__init__(detail or user_message)
        self.code = code
        self.user_message = user_message


def _image_reference(
        image_base64: str,
        role: str,
        label: str,
) -> ImageInputReference:
    encoded = image_base64.strip()
    if encoded.startswith("data:"):
        if "," not in encoded:
            raise ImageGenerationError(
                "invalid_input_reference",
                f"A referência {label} está em um formato inválido.",
                f"Malformed data URL for {label}.",
            )
        encoded = encoded.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(encoded, validate=True)
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = str(image.format or "").upper()
            image.verify()
    except (binascii.Error, ValueError, OSError) as error:
        raise ImageGenerationError(
            "invalid_input_reference",
            f"Não consegui ler a referência {label}.",
            f"Invalid {label}: {type(error).__name__}: {error}",
        ) from error

    mime_type = IMAGE_FORMAT_MIME_TYPES.get(image_format)
    if not mime_type:
        raise ImageGenerationError(
            "unsupported_input_reference",
            f"A referência {label} usa um formato de imagem não suportado.",
            f"Unsupported format for {label}: {image_format}",
        )

    return ImageInputReference(encoded, mime_type, role, label)


def _clean_image_request(
        raw_request: str,
        gork_user: User | None,
        referenced_users: list[User],
        me_user: User | None = None,
) -> str:
    request = raw_request

    if gork_user:
        request = _replace_user_identifiers(request, gork_user, "")

    for user in referenced_users:
        request = _replace_user_identifiers(request, user, user.name or "Usuário")

    if me_user:
        request = re.sub(
            r"(?<!\w)@me\b",
            me_user.name or "Usuário",
            request,
            flags=re.IGNORECASE,
        )

    request = re.sub(r"!image\b", "", request, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", request).strip()


def _replace_user_identifiers(text: str, user: User, replacement: str) -> str:
    identifiers = (
        f"@{user.phone_number}@s.whatsapp.net" if user.phone_number else "",
        f"{user.src_id}@lid" if user.src_id else "",
        f"@{user.src_id}" if user.src_id else "",
        f"@{user.phone_number}" if user.phone_number else "",
    )
    for identifier in identifiers:
        if identifier:
            text = text.replace(identifier, replacement)
    return text


def _exclude_gork_user(
        referenced_users: list[User],
        gork_user: User | None,
) -> list[User]:
    if not gork_user:
        return referenced_users
    return [user for user in referenced_users if user.id != gork_user.id]


def _build_image_prompt(
        system_prompt: str,
        user_request: str,
        references: list[ImageInputReference],
) -> str:
    if references:
        manifest_lines = [
            f"Reference [{index}]: role={reference.role}; label={reference.label}"
            for index, reference in enumerate(references, start=1)
        ]
    else:
        manifest_lines = ["No input references were provided."]

    manifest = "\n".join(manifest_lines)
    return (
        f"{system_prompt.strip()}\n\n"
        f"INPUT REFERENCE MANIFEST:\n{manifest}\n\n"
        f"USER REQUEST:\n{user_request.strip()}"
    )


async def _download_media_reference(
        message_id: str,
        role: str,
        label: str,
) -> ImageInputReference:
    try:
        image_base64, _ = await download_media(message_id)
    except Exception as error:
        raise ImageGenerationError(
            "input_reference_download_failed",
            f"Não consegui carregar a referência {label}.",
            f"Failed to download {label} ({message_id}): {type(error).__name__}: {error}",
        ) from error

    if not image_base64:
        raise ImageGenerationError(
            "input_reference_download_failed",
            f"Não consegui carregar a referência {label}.",
            f"Empty media response for {label} ({message_id}).",
        )
    return _image_reference(image_base64, role, label)


async def _include_quoted_author(
        referenced_users: list[User],
        quoted_message: Message | None,
        gork_user: User | None,
        user_repo: UserRepository,
        quoted_has_image_reference: bool = False,
) -> None:
    if quoted_has_image_reference:
        return
    if not quoted_message or not quoted_message.user_id:
        return
    if gork_user and quoted_message.user_id == gork_user.id:
        return
    if any(user.id == quoted_message.user_id for user in referenced_users):
        return

    quoted_user = await user_repo.find_by_id(quoted_message.user_id)
    if quoted_user:
        referenced_users.append(quoted_user)


def _provider_error(error: httpx.HTTPStatusError) -> ImageGenerationError:
    status = error.response.status_code
    response_text = error.response.text.lower()

    if "content-moderated" in response_text or "content moderation" in response_text:
        return ImageGenerationError(
            "content_moderated",
            "A geração foi bloqueada pela moderação do provedor. Tente reformular o pedido.",
            error.response.text[:1500],
        )
    if status == 429:
        return ImageGenerationError(
            "rate_limited",
            "O serviço de imagens está sobrecarregado agora. Tente novamente em alguns instantes.",
            error.response.text[:1500],
        )
    if status == 402:
        return ImageGenerationError(
            "provider_credits",
            "O serviço de imagens está temporariamente indisponível por limite de uso.",
            error.response.text[:1500],
        )
    if status in (401, 403):
        return ImageGenerationError(
            "provider_auth",
            "O serviço de imagens está com um problema de configuração.",
            error.response.text[:1500],
        )
    if status >= 500:
        return ImageGenerationError(
            "provider_unavailable",
            "O provedor de imagens está indisponível no momento. Tente novamente mais tarde.",
            error.response.text[:1500],
        )
    return ImageGenerationError(
        "provider_rejected_request",
        "O provedor não conseguiu processar esse pedido de imagem. Tente reformulá-lo.",
        error.response.text[:1500],
    )


def _extract_image_reference(response: dict) -> str:
    if not isinstance(response, dict):
        raise ImageGenerationError(
            "invalid_provider_response",
            "O provedor de imagens retornou uma resposta inválida. Tente novamente.",
            f"Invalid response type: {type(response).__name__}",
        )

    data = response.get("data")
    if isinstance(data, list) and data:
        first_image = data[0]
        if isinstance(first_image, dict):
            reference = first_image.get("b64_json") or first_image.get("url")
            if isinstance(reference, str) and reference.strip():
                return reference.strip()
        raise ImageGenerationError(
            "invalid_provider_response",
            "O provedor retornou uma imagem em formato inválido. Tente novamente.",
            "Image API response has no b64_json or URL.",
        )

    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ImageGenerationError(
            "invalid_provider_response",
            "O provedor de imagens retornou uma resposta vazia. Tente novamente.",
            "Response has no choices.",
        )

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    images = message.get("images") if isinstance(message, dict) else None
    if not isinstance(images, list) or not images:
        provider_error = response.get("error")
        raise ImageGenerationError(
            "image_not_generated",
            "Não foi possível gerar a imagem. Tente reformular o pedido ou tente novamente mais tarde.",
            f"Response has no images. Provider error: {provider_error}",
        )

    first_image = images[0]
    if not isinstance(first_image, dict):
        raise ImageGenerationError(
            "invalid_provider_response",
            "O provedor retornou uma imagem em formato inválido. Tente novamente.",
            f"Invalid image entry type: {type(first_image).__name__}",
        )

    image_url = first_image.get("image_url")
    reference = image_url.get("url") if isinstance(image_url, dict) else image_url
    if not isinstance(reference, str) or not reference.strip():
        raise ImageGenerationError(
            "invalid_provider_response",
            "O provedor retornou uma imagem em formato inválido. Tente novamente.",
            "Image URL is missing.",
        )
    return reference.strip()


async def _load_generated_image(reference: str) -> bytes:
    if reference.startswith("data:"):
        if "," not in reference:
            raise ImageGenerationError(
                "invalid_image_data",
                "A imagem gerada veio corrompida. Tente novamente.",
                "Malformed data URL.",
            )
        reference = reference.split(",", 1)[1]

    if reference.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                response = await client.get(reference)
                response.raise_for_status()
                image_bytes = response.content
        except httpx.HTTPError as error:
            raise ImageGenerationError(
                "image_download_failed",
                "A imagem foi gerada, mas não consegui baixá-la do provedor. Tente novamente.",
                str(error),
            ) from error
    else:
        try:
            image_bytes = base64.b64decode(reference, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ImageGenerationError(
                "invalid_image_data",
                "A imagem gerada veio corrompida. Tente novamente.",
                str(error),
            ) from error

    if not image_bytes or len(image_bytes) > MAX_GENERATED_IMAGE_BYTES:
        raise ImageGenerationError(
            "invalid_image_size",
            "A imagem gerada veio vazia ou grande demais. Tente novamente.",
            f"Generated image size: {len(image_bytes)} bytes.",
        )
    return image_bytes


async def generate_image(
        user_id: int,
        db_message: Message,
        action_params: Optional[dict] = None,
        context: Optional[dict] = None,
) -> ImageGenerationResult:
    try:
        image_base64 = await _generate_image(
            user_id,
            db_message,
            action_params,
            context,
        )
        return ImageGenerationResult(success=True, image_base64=image_base64)
    except ImageGenerationError as error:
        await _log_generation_error(error.code, str(error))
        return ImageGenerationResult(
            success=False,
            error_code=error.code,
            user_message=error.user_message,
        )
    except httpx.HTTPStatusError as error:
        mapped_error = _provider_error(error)
        await _log_generation_error(mapped_error.code, str(mapped_error))
        return ImageGenerationResult(
            success=False,
            error_code=mapped_error.code,
            user_message=mapped_error.user_message,
        )
    except httpx.TimeoutException as error:
        await _log_generation_error("provider_timeout", str(error))
        return ImageGenerationResult(
            success=False,
            error_code="provider_timeout",
            user_message="A geração da imagem demorou demais e expirou. Tente novamente.",
        )
    except httpx.RequestError as error:
        await _log_generation_error("provider_connection", str(error))
        return ImageGenerationResult(
            success=False,
            error_code="provider_connection",
            user_message="Não consegui conectar ao serviço de imagens. Tente novamente mais tarde.",
        )
    except Exception as error:
        await _log_generation_error(
            "unexpected_error", f"{type(error).__name__}: {error}"
        )
        return ImageGenerationResult(
            success=False,
            error_code="unexpected_error",
            user_message="Tive um problema inesperado ao gerar a imagem. Tente novamente.",
        )


async def _log_generation_error(code: str, detail: str) -> None:
    try:
        await logger.error("ImageGeneration", code, detail)
    except Exception:
        # Logging must never turn a handled generation failure into a silent task crash.
        pass


async def _generate_image(
        user_id: int,
        db_message: Message,
        action_params: Optional[dict] = None,
        context: Optional[dict] = None,
) -> str:
    identity_photos: list[tuple[str, User]] = []
    
    async with PgConnection() as db:
        agent_repo = AgentRepository(db)
        user_repo = UserRepository(db)
        message_repo = MessageRepository(db)
        model_conversation_repo = ModelConversationRepository(db)
        command_repo = CommandRepository(Command, db)

        modify_image_agent = await agent_repo.find_by_name("modify-image")
        if not modify_image_agent:
            raise ImageGenerationError(
                "agent_not_configured",
                "O agente de geração de imagens não está configurado.",
            )

        image_system_prompt = modify_image_agent.prompt

        gork_user = await user_repo.find_by_phone_or_id(INSTANCE_NUMBER)

        raw_user_message = ""
        if action_params and action_params.get("prompt"):
            raw_user_message = str(action_params.get("prompt"))
        elif db_message and db_message.content:
            raw_user_message = db_message.content

        # Fetch explicitly mentioned users
        mentions = await get_mentions_from_content(db_message, db) if db_message else []
        explicitly_referenced_user_ids = {mention.id for mention in mentions}

        # Also support mentions passed in action_params
        if action_params and action_params.get("mentioned_users"):
            for u_id in action_params.get("mentioned_users", []):
                u_obj = None
                if isinstance(u_id, int):
                    u_obj = await user_repo.find_by_id(u_id)
                else:
                    try:
                        u_obj = await user_repo.find_by_id(int(u_id))
                    except (ValueError, TypeError):
                        u_obj = await user_repo.find_by_phone_or_id(str(u_id))
                if u_obj and all(m.id != u_obj.id for m in mentions):
                    mentions.append(u_obj)
                if u_obj:
                    explicitly_referenced_user_ids.add(u_obj.id)

        me_user = None
        if _has_me_mention(raw_user_message):
            me_user = await user_repo.find_by_id(user_id)
            if me_user and all(user.id != me_user.id for user in mentions):
                mentions.append(me_user)
            if me_user:
                explicitly_referenced_user_ids.add(me_user.id)

        if gork_user:
            mentions = _exclude_gork_user(mentions, gork_user)
            explicitly_referenced_user_ids.discard(gork_user.id)

        # Quoted message handling
        quoted_message = await message_repo.find_by_id(db_message.quoted_message_id) if db_message and db_message.quoted_message_id else None
        quoted_image_id = (
            context.get("image_quote")
            if context and context.get("image_quote")
            else (
                quoted_message.message_id
                if quoted_message and quoted_message.media_id
                else None
            )
        )

        await _include_quoted_author(
            mentions,
            quoted_message,
            gork_user,
            user_repo,
            quoted_has_image_reference=bool(quoted_image_id),
        )

        user_message = _clean_image_request(
            raw_user_message,
            gork_user,
            mentions,
            me_user=me_user,
        )
        if not user_message:
            raise ImageGenerationError(
                "empty_image_request",
                "Descreva o que você quer gerar ou modificar com o comando !image.",
            )

        users_with_profile = [user for user in mentions if user.profile_pic_path]
        missing_required_profiles = [
            user.name or "Usuário"
            for user in mentions
            if user.id in explicitly_referenced_user_ids and not user.profile_pic_path
        ]
        if missing_required_profiles:
            names = ", ".join(missing_required_profiles)
            raise ImageGenerationError(
                "identity_reference_unavailable",
                f"Não encontrei uma foto de perfil para usar como referência: {names}.",
            )

        if users_with_profile:
            s3_client = S3Client()
            try:
                await s3_client.connect()
                for mention in users_with_profile:
                    photo_base64 = await s3_client.get_image_base64(
                        "whatsapp",
                        mention.profile_pic_path,
                    )
                    if not photo_base64:
                        raise ValueError("empty profile image")
                    identity_photos.append((photo_base64, mention))
            except Exception as error:
                raise ImageGenerationError(
                    "identity_reference_unavailable",
                    "Não consegui carregar uma das fotos de perfil usadas como referência.",
                    f"{type(error).__name__}: {error}",
                ) from error

        new_command = await command_repo.create_command(
            command="image",
            user_id=user_id,
            group_id=db_message.group_id if db_message else None,
        )

        interaction_repo = InteractionRepository(Interaction, db)

        image_model = await model_conversation_repo.resolve_agent_model(
            modify_image_agent,
            user_id=user_id,
            group_id=db_message.group_id if db_message else None,
        )
        if not image_model:
            raise ImageGenerationError(
                "model_not_configured",
                "O modelo de geração de imagens não está configurado.",
            )

        message_image_id = (
            context.get("image_message")
            if context and context.get("image_message")
            else db_message.message_id if db_message and db_message.media_id else None
        )
        references: list[ImageInputReference] = []
        if message_image_id:
            references.append(
                await _download_media_reference(
                    message_image_id,
                    "primary",
                    "imagem principal da mensagem",
                )
            )
        if quoted_image_id:
            quoted_role = "context" if references else "primary"
            references.append(
                await _download_media_reference(
                    quoted_image_id,
                    quoted_role,
                    "imagem da mensagem citada",
                )
            )
        for photo_base64, user in identity_photos:
            references.append(
                _image_reference(
                    photo_base64,
                    "identity",
                    f"foto de identidade de {user.name or 'Usuário'}",
                )
            )

        payload = {
            "model": image_model.openrouter_id,
            "prompt": _build_image_prompt(
                image_system_prompt,
                user_message,
                references,
            ),
        }
        if references:
            payload["input_references"] = [
                reference.payload_item() for reference in references
            ]

        req = await generate_images(payload)
        usage = req.get("usage") if isinstance(req, dict) else {}
        usage = usage if isinstance(usage, dict) else {}

        try:
            image_reference = _extract_image_reference(req)
        except ImageGenerationError:
            try:
                await interaction_repo.create_interaction(
                    model_id=image_model.id,
                    user_id=user_id,
                    command_id=new_command.id,
                    user_prompt=user_message,
                    response=None,
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    group_id=db_message.group_id if db_message else None,
                )
            except Exception as interaction_error:
                await _log_generation_error(
                    "interaction_log_failed", str(interaction_error)
                )
            raise

        image_bytes = await _load_generated_image(image_reference)

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
                if image.mode != "RGBA":
                    image = image.convert("RGBA")

                buffer = BytesIO()
                image.save(buffer, format="PNG")
                output_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception as error:
            raise ImageGenerationError(
                "invalid_generated_image",
                "O provedor retornou uma imagem inválida ou corrompida. Tente novamente.",
                f"{type(error).__name__}: {error}",
            ) from error

        try:
            await interaction_repo.create_interaction(
                model_id=image_model.id,
                user_id=user_id,
                command_id=new_command.id,
                user_prompt=user_message,
                response=output_base64,
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                group_id=db_message.group_id if db_message else None,
            )
        except Exception as interaction_error:
            await _log_generation_error("interaction_log_failed", str(interaction_error))

        return output_base64
