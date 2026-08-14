import base64
import binascii
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
from utils import INSTANCE_NUMBER


MAX_GENERATED_IMAGE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class ImageGenerationResult:
    success: bool
    image_base64: str | None = None
    error_code: str | None = None
    user_message: str | None = None


class ImageGenerationError(Exception):
    def __init__(self, code: str, user_message: str, detail: str = ""):
        super().__init__(detail or user_message)
        self.code = code
        self.user_message = user_message


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
) -> ImageGenerationResult:
    try:
        image_base64 = await _generate_image(user_id, db_message, action_params)
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
) -> str:
    mention_photo: list[tuple[str, User]] = []
    
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

        if gork_user:
            user_message = (
                raw_user_message
                .replace(f"@{gork_user.phone_number}@s.whatsapp.net", "")
                .replace(f"{gork_user.src_id}@lid", "")
                .replace(f"@{gork_user.src_id}", "")
            )
        else:
            user_message = raw_user_message

        # Fetch explicitly mentioned users
        mentions = await get_mentions_from_content(db_message, db) if db_message else []

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

        # Quoted message handling
        quoted_message = await message_repo.find_by_id(db_message.quoted_message_id) if db_message and db_message.quoted_message_id else None

        if mentions:
            s3_client = S3Client()
            await s3_client.connect()
            for mention in mentions:
                if gork_user and mention.phone_number == gork_user.phone_number:
                    continue
                if mention and mention.profile_pic_path:
                    try:
                        photo_base64 = await s3_client.get_image_base64("whatsapp", mention.profile_pic_path)
                        if photo_base64:
                            mention_photo.append((photo_base64, mention))
                    except Exception:
                        pass

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

        # Collect images from the message itself and from the quoted message
        message_image_base64 = None
        quoted_image_base64 = None

        if db_message and db_message.media_id and db_message.message_id:
            try:
                res, _ = await download_media(db_message.message_id)
                if res:
                    message_image_base64 = res
            except Exception:
                message_image_base64 = None

        if quoted_message and quoted_message.media_id and quoted_message.message_id:
            try:
                res, _ = await download_media(quoted_message.message_id)
                if res:
                    quoted_image_base64 = res
            except Exception:
                quoted_image_base64 = None

        # Determine which is the "principal" image:
        # - If the message itself has an image, it's the principal
        # - Otherwise, the quoted image becomes the principal
        if message_image_base64:
            primary_image_base64 = message_image_base64
            secondary_image_base64 = quoted_image_base64
        else:
            primary_image_base64 = quoted_image_base64
            secondary_image_base64 = None

        photo_context = ""
        if mention_photo:
            for idx, (_, us) in enumerate(mention_photo, start=1):
                offset = 1
                if primary_image_base64:
                    offset += 1
                if secondary_image_base64:
                    offset += 1
                idx = idx + offset - 1
                user_message = user_message.replace(f"@{us.phone_number}@s.whatsapp.net", us.name or "Usuário").replace(f"{us.src_id}@lid", us.name or "Usuário").replace(f"@{us.src_id}", us.name or "Usuário")
                photo_context = f"{photo_context}Foto [{idx}]: É a pessoa: {us.name or 'Usuário'}\n"

        base64_context = ""
        if primary_image_base64 and secondary_image_base64:
            base64_context = (
                "A primeira foto é chamada de 'principal'. A segunda foto é uma imagem de referência/contexto adicional. "
                "Leve ambas em consideração quando analisar a requisição final do usuario."
            )
        elif primary_image_base64:
            base64_context = (
                "A primeira foto é chamada de 'principal'. Leve isso em consideração quando analisar a requisição final do usuario."
            )

        final_message = ""
        if base64_context:
            final_message = f"{base64_context}\n"
        if photo_context:
            final_message = f"{final_message}{photo_context}\n\n"

        user_message = f"{final_message}\n\n{user_message}"
        messages_content = [
            {
                "type": "text",
                "text": user_message
            }
        ]

        if primary_image_base64:
            data_url = f"data:image/jpeg;base64,{primary_image_base64}"
            messages_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                }
            )

        if secondary_image_base64:
            data_url = f"data:image/jpeg;base64,{secondary_image_base64}"
            messages_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                }
            )

        if mention_photo:
            for photo, _ in mention_photo:
                data_url = f"data:image/jpeg;base64,{photo}"
                messages_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url
                        }
                    }
                )

        payload = {
            "model": image_model.openrouter_id,
            "prompt": f"{image_system_prompt}\n\nUSER REQUEST:\n{user_message}",
        }
        input_references = [
            item
            for item in messages_content
            if isinstance(item, dict) and item.get("type") == "image_url"
        ]
        if input_references:
            payload["input_references"] = input_references

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
