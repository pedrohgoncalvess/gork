import base64
import re
from io import BytesIO

import httpx
from PIL import Image
from rembg import new_session, remove
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.sticker_caption import add_caption_to_image
from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from external.evolution import download_media
from s3 import S3Client
from utils import get_env_var


NINJA_KEY = get_env_var("NINJA_KEY")

def _resize_contain_transparent(img: Image.Image, size: tuple) -> Image.Image:
    target_w, target_h = size

    img.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)

    canvas = Image.new('RGBA', (target_w, target_h), (0, 0, 0, 0))

    offset_x = (target_w - img.width) // 2
    offset_y = (target_h - img.height) // 2
    canvas.paste(img, (offset_x, offset_y), mask=img.split()[3])

    return canvas


def _resize_cover(img: Image.Image, size: tuple) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / img.width, target_h / img.height)
    resized_w = round(img.width * scale)
    resized_h = round(img.height * scale)

    resized = img.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    left = (resized_w - target_w) // 2
    top = (resized_h - target_h) // 2

    return resized.crop((left, top, left + target_w, top + target_h))


async def static_sticker(
        db_message: Message,
        db: AsyncSession, random_image: bool = False,
        remove_background: bool = False, fill: bool = False,
        gork_req: bool = False,
        source_image_bytes: bytes | None = None,
        caption_text: str | None = None,
) -> str:
    message_repo = MessageRepository(db)

    quoted_message = await message_repo.find_by_id(
        db_message.quoted_message_id
    ) if db_message.quoted_message_id else None

    if caption_text is None:
        caption_text = clean_text(db_message.content) if db_message.content else None
    if not caption_text and quoted_message:
        caption_text = clean_text(quoted_message.content) if quoted_message.content else None

    image_base64 = None

    if db_message.media_id and source_image_bytes is None:
        image_base64, _ = await download_media(db_message.message_id)
    if quoted_message and quoted_message.media_id and image_base64 is None and source_image_bytes is None:
        image_base64, _ = await download_media(quoted_message.message_id)
    if image_base64 is None and source_image_bytes is None and quoted_message:
        user_repo = UserRepository(db)
        user = await user_repo.find_by_id(quoted_message.user_id) if not gork_req else await user_repo.find_by_id(db_message.user_id)
        if caption_text:
            pattern = r'@(\d+)'
            mentions = re.findall(pattern, caption_text)
            users_mentioned = [await user_repo.find_by_phone_or_id(mention) for mention in mentions]
            users_mentions = zip(users_mentioned, mentions)
            for user_m, mention in users_mentions:
                caption_text = caption_text.replace(f"@{mention}", user_m.name)
        if user.profile_pic_path:
            s3_client = S3Client()
            _ = await s3_client.connect()
            image_base64 = await s3_client.get_image_base64("whatsapp", user.profile_pic_path)
    if random_image or image_base64 is None:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.api-ninjas.com/v1/randomimage", headers={"X-Api-Key": NINJA_KEY}
            )
            source_image_bytes = response.content

    image_bytes = source_image_bytes or base64.b64decode(image_base64)
    img = Image.open(BytesIO(image_bytes))

    if remove_background:
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        output = remove(img_bytes.read(), session=new_session("u2net_human_seg"))
        img = Image.open(BytesIO(output))

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    if fill:
        img = _resize_cover(img, (512, 512))
    else:
        img = _resize_contain_transparent(img, (512, 512))

    if caption_text:
        img = add_caption_to_image(img, caption_text)

    buffer = BytesIO()
    img.save(buffer, format='WEBP', quality=95)
    buffer.seek(0)
    webp_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return webp_base64
