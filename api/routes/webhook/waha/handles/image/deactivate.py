import asyncio
import base64
import re
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.content import MediaRepository, MessageRepository
from external.waha import download_media, send_image, send_message
from log import logger
from s3 import S3Client
from utils import get_instance_number, project_root


def render_deactivated_image(source: bytes) -> str:
    """Preserve the photo's proportions and append the reference's account footer."""
    with Image.open(BytesIO(source)) as original:
        photo = ImageOps.exif_transpose(original).convert("RGBA")
    background = Image.new("RGBA", photo.size, "white")
    photo = ImageOps.grayscale(Image.alpha_composite(background, photo)).convert("RGB")
    # Bound output size, while keeping the label legible on small source images.
    width = max(320, min(photo.width, 1600))
    photo = photo.resize((width, max(1, round(photo.height * width / photo.width))), Image.Resampling.LANCZOS)
    scale = width / 209
    footer_height = round(29 * scale)
    canvas = Image.new("RGB", (width, photo.height + footer_height), (54, 57, 59))
    canvas.paste(photo, (0, 0))
    draw = ImageDraw.Draw(canvas)
    color = (151, 153, 154)
    font = ImageFont.truetype(str(Path(project_root) / "assets/fonts/arial-bold.ttf"), round(10 * scale))
    draw.text((30 * scale, photo.height + footer_height / 2), "Deactivated account", font=font, fill=color, anchor="lm")

    # Draw the small trash icon directly so it stays monochrome on every host.
    x, y = 15 * scale, photo.height + (footer_height - 9 * scale) / 2
    draw.rectangle((x, y + 2 * scale, x + 7 * scale, y + 3 * scale), fill=color)
    draw.rectangle((x + 2 * scale, y, x + 5 * scale, y + scale), fill=color)
    draw.polygon([(x + scale, y + 4 * scale), (x + 6 * scale, y + 4 * scale),
                  (x + 5 * scale, y + 9 * scale), (x + 2 * scale, y + 9 * scale)], fill=color)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


async def _stored_image(bucket: str, path: str) -> bytes:
    client = S3Client()
    await client.connect()
    return base64.b64decode(await client.get_image_base64(bucket, path), validate=True)


async def _random_photo() -> bytes:
    from api.routes.webhook.waha.handles.image.sticker_static import _random_image

    image = await _random_image()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def _source_image(db_message: Message, db: AsyncSession, context: dict) -> bytes | None:
    quoted = (
        await MessageRepository(db).find_by_id(db_message.quoted_message_id)
        if db_message.quoted_message_id else None
    )
    source_id = context.get("image_quote") or context.get("image_message")
    media_id = quoted.media_id if quoted and quoted.media_id else db_message.media_id
    if not source_id and media_id:
        source_id = quoted.message_id if quoted and quoted.media_id else db_message.message_id
    if source_id:
        try:
            encoded, _ = await download_media(source_id)
            if encoded:
                return base64.b64decode(encoded, validate=True)
        except Exception:
            # WAHA may have expired the media; try our saved copy.
            pass
        if media_id:
            media = await MediaRepository(db).find_by_id(media_id)
            if media:
                return await _stored_image(media.bucket, media.path)
        raise ValueError("quoted image unavailable")

    repository = UserRepository(db)
    mentions = list(dict.fromkeys(re.findall(r"@(\d{7,25})", db_message.content or "")))
    if mentions:
        bot_number = await get_instance_number()
        bot = await repository.find_by_phone(bot_number)
        bot_identifiers = {bot_number}
        if bot:
            bot_identifiers.update((bot.phone_number, bot.src_id))
        mentions = [mention for mention in mentions if mention not in bot_identifiers]
    for mention in mentions:
        user = await repository.find_by_phone_or_id(mention)
        if user and user.profile_pic_path:
            return await _stored_image("whatsapp", user.profile_pic_path)
    if not mentions and not db_message.quoted_message_id and not context.get("text_quote"):
        return await _random_photo()
    return None


async def handle_deactivate_command(
    remote_id: str, db_message: Message, db: AsyncSession, context: dict | None = None,
) -> None:
    try:
        source = await _source_image(db_message, db, context or {})
        if source is None:
            await send_message(remote_id, "Responda a uma foto com !deactivate ou use !deactivate @usuário (com foto de perfil salva).", db_message.message_id)
            return
        result = await asyncio.to_thread(render_deactivated_image, source)
    except Exception as error:
        await logger.error("Deactivate", "ImageFailed", f"message_id={db_message.message_id} error={type(error).__name__}: {error}")
        await send_message(remote_id, "Não consegui carregar essa foto. Tente outra imagem ou mencione alguém com foto de perfil salva.", db_message.message_id)
        return
    await send_image(remote_id, result, filename="deactivated.png", mimetype="image/png")
