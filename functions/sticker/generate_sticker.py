import base64
from io import BytesIO
import re

import httpx
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from external.evolution import download_media
from functions.sticker import add_caption_to_image
from s3 import S3Client
from services import verifiy_media
from utils import get_env_var


async def generate_sticker(webhook_event: dict, caption_text: str, db: AsyncSession, random_image: bool = False) -> str:
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]
    medias = verifiy_media(webhook_event)

    image_base64 = None

    available_medias = list(medias.keys())
    if "text_quote" in available_medias:
        message_text, quoted_message_id = medias["text_quote"]
        message_repo = MessageRepository(Message, db)

        message = await message_repo.find_by_message_id(quoted_message_id)
        caption_text = message_text if message_text else caption_text
    else:
        message = None

    if "image_message" in available_medias and image_base64 is None:
        image_base64, _ = await download_media(message_id)
    if "image_quote" in available_medias and image_base64 is None:
        image_base64, _ = await download_media(medias["image_quote"])
    if image_base64 is None and message:
        user_repo = UserRepository(User, db)
        user = await user_repo.find_by_id(message.user_id)

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
            response = await client.get("https://api.api-ninjas.com/v1/randomimage", headers={"X-Api-Key": get_env_var("NINJA_KEY")})
            image_base64 = response.content

    image_bytes = base64.b64decode(image_base64)

    img = Image.open(BytesIO(image_bytes))
    img.thumbnail((512, 512), Image.Resampling.LANCZOS)

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    if caption_text:
        img = add_caption_to_image(img, caption_text)

    buffer = BytesIO()
    img.save(buffer, format='WEBP', quality=95)
    buffer.seek(0)
    webp_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return webp_base64