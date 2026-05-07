from typing import List

from api.routes.webhook.evolution.processors.group import INSTANCE_NUMBER
from database.models.base import User
from s3 import S3Client


async def get_pictures(mentions: List[User]) -> list[tuple[str, str]]:
    s3_client = S3Client()
    pictures = []
    for mention in mentions:
        if mention.profile_pic_path:
            if not mention.phone_number == INSTANCE_NUMBER:
                _ = await s3_client.connect()
                image_base64 = await s3_client.get_image_base64("whatsapp", mention.profile_pic_path)
                pictures.append(("picture", image_base64))
        else:
            pictures.append((None, f"O vagabundo {mention.name} não tem foto salva."))

    return pictures
