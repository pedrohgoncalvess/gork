from sqlalchemy.ext.asyncio import AsyncSession

from database.models.base import User
from database.operations.base import UserRepository
from s3 import S3Client


async def get_pictures(message_context: dict[str, any], db: AsyncSession) -> list[tuple[str, str]]:

    mentions = message_context.get("mentions")
    user_repo = UserRepository(User, db)

    s3_client = S3Client()
    pictures = []
    for mention in mentions:
        user = await user_repo.find_by_phone_or_id(mention)
        if user.profile_pic_path:
            if not user.name == "Gork":
                _ = await s3_client.connect()
                image_base64 = await s3_client.get_image_base64("whatsapp", user.profile_pic_path)
                pictures.append(("picture", image_base64))
        else:
            pictures.append((None, f"O vagabundo {user.name} não tem foto salva."))

    return pictures