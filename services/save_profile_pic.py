import httpx

from database import PgConnection
from database.operations.base import UserRepository
from database.models.base import User
from external.evolution import get_profile_info
from s3 import S3Client


async def save_profile_pic(
        user_id: int,
        max_size: tuple[float, float] = (1920, 1920)
) -> None:
    async with PgConnection() as db:
        user_repo = UserRepository(db)
        user = await user_repo.find_by_id(user_id)
        if user.profile_pic_path is not None:
            return user

        profile_infos = await get_profile_info(user.phone_number)
        image_url = profile_infos.get("picture")

        if image_url is None:
            return user

        async with httpx.AsyncClient() as client:
            response = await client.get(image_url)
            response.raise_for_status()
            image_bytes = response.content

    s3_client = S3Client()

    object_path = f"profile/{user.ext_id}.jpeg"
    _ = await s3_client.connect()
    _ = await s3_client.upload_image(
        image_source=image_bytes,
        max_size=max_size,
        object_name=object_path,
    )

    _ = await user_repo.update(user.id, {"profile_pic_path": object_path})