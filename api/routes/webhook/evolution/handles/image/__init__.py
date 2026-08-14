import base64
from io import BytesIO
from typing import Optional, List

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.describe_image import describe_image_agent
from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.gallery import list_images, search_images
from api.routes.webhook.evolution.handles.image.generate import generate_image
from api.routes.webhook.evolution.handles.image.picture import get_pictures
from api.routes.webhook.evolution.handles.social import download_twitter_media, extract_twitter_url
from database.models.base import User
from database.models.content import Message
from database.operations.content import MessageRepository, MediaRepository
from external.evolution import download_media, send_animated_sticker, send_image, send_message, send_sticker
from log import logger
from s3 import S3Client
from services import parse_params


def _param_enabled(value) -> bool:
    return str(value).lower() in ["true", "t", "1", "yes", "y"]


def _remove_background_enabled(params: dict) -> bool:
    return any(
        _param_enabled(params.get(key, "false"))
        for key in ("no-background", "no-backgorund")
    )


def _parse_blur(params: dict) -> int:
    val = params.get("blur", 0)
    try:
        blur = int(val)
    except (ValueError, TypeError):
        blur = 0
    return max(0, min(100, blur))


def _media_type_is_video(media_type: str | None) -> bool:
    return media_type in ("mp4", "video")


def _media_type_is_sticker(media_type: str | None) -> bool:
    return media_type in ("webp", "sticker")


def _sticker_is_animated(media_bytes: bytes) -> bool:
    try:
        with Image.open(BytesIO(media_bytes)) as image:
            return bool(getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1)
    except Exception:
        return False


def _context_media_kind(context: dict | None, source: str) -> str | None:
    if not context:
        return None

    if source == "message":
        if context.get("video_message"):
            return "video"
        if context.get("sticker_message"):
            return "sticker"
        if context.get("image_message"):
            return "image"
    elif source == "quoted":
        if context.get("video_quote"):
            return "video"
        if context.get("sticker_quote"):
            return "sticker"
        if context.get("image_quote"):
            return "image"

    return None


async def _download_media_bytes_from_message_id(message_id: str | None) -> bytes | None:
    if not message_id:
        return None

    try:
        media_base64, _ = await download_media(message_id)
    except Exception:
        return None

    if not media_base64:
        return None

    return base64.b64decode(media_base64)


async def _load_source_media_bytes(source_message: Message, media=None) -> bytes | None:
    source_bytes = await _download_media_bytes_from_message_id(source_message.message_id)
    if source_bytes or media is None:
        return source_bytes

    try:
        s3_client = S3Client()
        await s3_client.connect()
        media_base64 = await s3_client.get_image_base64(media.bucket, media.path)
        return base64.b64decode(media_base64)
    except Exception:
        return None


async def handle_image_command(
        remote_id: str,
        user_id: int,
        db_message: Message,
        action_params: Optional[dict] = None,
):
    try:
        result = await generate_image(user_id, db_message, action_params=action_params)
    except Exception as error:
        await _log_image_command_error(
            "unhandled_generation_error", f"{type(error).__name__}: {error}"
        )
        await _send_image_error(
            remote_id,
            "Tive um problema inesperado ao gerar a imagem. Tente novamente.",
            db_message,
        )
        return

    if not result.success or not result.image_base64:
        await _send_image_error(
            remote_id,
            result.user_message or "Não foi possível gerar a imagem. Tente novamente.",
            db_message,
        )
        return

    try:
        await send_image(
            remote_id,
            result.image_base64,
            filename="gork.png",
            mimetype="image/png",
        )
    except Exception as error:
        await _log_image_command_error(
            "image_send_failed", f"{type(error).__name__}: {error}"
        )
        await _send_image_error(
            remote_id,
            "A imagem foi gerada, mas não consegui enviá-la. Tente novamente.",
            db_message,
        )


async def _log_image_command_error(code: str, detail: str) -> None:
    try:
        await logger.error("ImageGeneration", code, detail)
    except Exception:
        pass


async def _send_image_error(
        remote_id: str,
        message: str,
        db_message: Message | None,
) -> None:
    try:
        await send_message(
            remote_id,
            message,
            db_message.message_id if db_message else None,
        )
    except Exception as error:
        await _log_image_command_error(
            "error_response_send_failed", f"{type(error).__name__}: {error}"
        )


async def handle_sticker_command(
        remote_id: str,
        db_message: Message,
        db: AsyncSession,
        context: dict | None = None,
        action_params: dict | None = None,
):
    message_repo = MessageRepository(db)
    params = parse_params(db_message.content if db_message and db_message.content else "")
    if action_params:
        for k, v in action_params.items():
            norm_key = k.replace("_", "-")
            if norm_key not in params and k not in params:
                params[norm_key] = str(v).lower() if isinstance(v, bool) else str(v)
    twitter_url = params.get("url") or extract_twitter_url(db_message.content if db_message and db_message.content else "")
    if twitter_url:
        result = await download_twitter_media(twitter_url)
        if not result.is_success:
            await send_message(remote_id, f"Erro ao baixar midia do Twitter/X: {result.error}")
            return

        effect = params.get("effect")
        fill = _param_enabled(params.get("fill", "false"))
        font_size = params.get("font-size", "l")
        remove_background = _remove_background_enabled(params)
        speed = float(params.get("speed", 1.0))
        cut_spec = params.get("cut")
        blur = _parse_blur(params)
        caption_text = clean_text(db_message.content).replace(twitter_url, "").strip()
        if result.media_type == "video":
            from api.routes.webhook.evolution.handles.image.sticker_animated import animated_sticker_from_bytes

            sticker_url = await animated_sticker_from_bytes(
                result.media_bytes,
                caption_text,
                effect,
                fill,
                font_size,
                remove_background=remove_background,
                speed=speed,
                cut_spec=cut_spec,
                blur=blur,
            )
            await send_animated_sticker(remote_id, sticker_url)
        else:
            from api.routes.webhook.evolution.handles.image.sticker_static import static_sticker

            is_random = _param_enabled(params.get("random", "false"))
            blur = _parse_blur(params)
            webp_base64 = await static_sticker(
                db_message,
                db,
                is_random,
                remove_background,
                fill,
                blur=blur,
                font_size_param=font_size,
                source_image_bytes=result.media_bytes,
                caption_text=caption_text,
            )
            await send_sticker(remote_id, webp_base64)
        return

    quoted_message = (
        await message_repo.find_by_id(db_message.quoted_message_id)
        if db_message.quoted_message_id
        else None
    )

    source_message = db_message
    source_kind = _context_media_kind(context, "message")
    source_media = None
    if db_message.media_id:
        media_repo = MediaRepository(db)
        media = await media_repo.find_by_id(db_message.media_id)
        if media:
            source_media = media
            if _media_type_is_video(media.type):
                source_kind = "video"
            elif _media_type_is_sticker(media.type):
                source_kind = "sticker"
            else:
                source_kind = "image"

    if not source_kind and quoted_message:
        source_message = quoted_message
        source_kind = _context_media_kind(context, "quoted")
        if quoted_message.media_id:
            media_repo = MediaRepository(db)
            media = await media_repo.find_by_id(quoted_message.media_id)
            if media:
                source_media = media
                if _media_type_is_video(media.type):
                    source_kind = "video"
                elif _media_type_is_sticker(media.type):
                    source_kind = "sticker"
                else:
                    source_kind = "image"

    source_bytes = None
    if source_message and source_kind in ("video", "sticker"):
        source_bytes = await _load_source_media_bytes(source_message, source_media)
        if source_kind == "sticker" and source_bytes and _sticker_is_animated(source_bytes):
            source_kind = "animated_sticker"

    if source_message and source_kind in ("video", "animated_sticker"):
        from api.routes.webhook.evolution.handles.image.sticker_animated import (
            animated_sticker,
            animated_sticker_from_bytes,
        )

        effect = params.get("effect")
        fill = _param_enabled(params.get("fill", "false"))
        font_size = params.get("font-size", "l")
        remove_background = _remove_background_enabled(params)
        speed = float(params.get("speed", 1.0))
        cut_spec = params.get("cut")
        blur = _parse_blur(params)

        caption_text = clean_text(db_message.content) if db_message.content else None
        if not caption_text and source_message.content:
            caption_text = clean_text(source_message.content) if source_message.content else None

        if source_bytes:
            gif_url = await animated_sticker_from_bytes(
                source_bytes,
                caption_text,
                effect,
                fill,
                font_size,
                remove_background=remove_background,
                speed=speed,
                cut_spec=cut_spec,
                blur=blur,
            )
        else:
            gif_url = await animated_sticker(
                source_message,
                effect,
                fill,
                font_size,
                caption_text,
                remove_background=remove_background,
                speed=speed,
                cut_spec=cut_spec,
                blur=blur,
            )
        await send_animated_sticker(remote_id, gif_url)
        return

    is_random = _param_enabled(params.get("random", "false"))
    remove_background = _remove_background_enabled(params)
    fill = _param_enabled(params.get("fill", "false"))
    font_size = params.get("font-size", "l")
    blur = _parse_blur(params)
    from api.routes.webhook.evolution.handles.image.sticker_static import static_sticker

    webp_base64 = await static_sticker(
        db_message,
        db,
        is_random,
        remove_background,
        fill,
        blur=blur,
        font_size_param=font_size,
        context=context,
    )
    await send_sticker(remote_id, webp_base64)


async def handle_describe_image_command(
        remote_id: str,
        db_message: Message,
        user_id: int,
        db: AsyncSession,
        group_id: Optional[int] = None
):
    error_message = "Não encontrei uma imagem para descrever."
    if db_message.media_id:
        message = db_message
    else:
        if not db_message.quoted_message_id:
            await send_message(remote_id, error_message)
            return

        message_repo = MessageRepository(db)
        quoted_message = await message_repo.find_by_id(db_message.quoted_message_id)

        if not quoted_message or not quoted_message.media_id:
            await send_message(remote_id, error_message)
            return

        message = quoted_message

    resume = await describe_image_agent(db, user_id, message)
    await send_message(remote_id, resume)
    return


async def handle_list_images_command(
        remote_id: str,
        db_message: Message | str | None,
        db: AsyncSession,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None
):
    if isinstance(db_message, Message):
        raw_text = db_message.content or ""
    elif isinstance(db_message, str):
        raw_text = db_message
    else:
        raw_text = ""

    treated_text = clean_text(raw_text)
    if treated_text:
        message = await search_images(
            treated_text, user_id=user_id, group_id=group_id, db=db
        )
    else:
        params = parse_params(raw_text)

        total_param = _param_enabled(params.get("total", "false"))

        message = await list_images(
            user_id=user_id if not group_id else None,
            group_id=group_id,
            db=db, total=total_param
        )
    await send_message(remote_id, message)
    return


async def handle_picture_command(
    remote_id: str,
    mentions: List[User],
):

    if len(mentions) == 0:
        await send_message(remote_id, "Ninguém foi mencionado.")

    pictures_for_send = await get_pictures(mentions)

    for type_, picture in pictures_for_send:
        if type_:
            await send_image(remote_id, picture)
        else:
            await send_message(remote_id, picture)

    return
