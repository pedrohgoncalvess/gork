from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.describe_image import describe_image_agent
from api.routes.webhook.evolution.handles.image.gallery import list_images, search_images
from api.routes.webhook.evolution.handles.image.generate import generate_image
from api.routes.webhook.evolution.handles.image.picture import get_pictures
from api.routes.webhook.evolution.handles.image.sticker_animated import animated_sticker
from api.routes.webhook.evolution.handles.image.sticker_static import static_sticker
from database.models.base import User
from database.models.content import Message
from database.operations.content import MessageRepository, MediaRepository
from external.evolution import send_animated_sticker, send_image, send_message, send_sticker
from services import parse_params


def _param_enabled(value) -> bool:
    return str(value).lower() in ["true", "t", "1", "yes", "y"]


async def handle_image_command(
        remote_id: str,
        user_id: int,
        db_message: Message,
):
    image_base64, error = await generate_image(user_id, db_message)
    if error:
        await send_message(remote_id, image_base64)
        return

    await send_image(remote_id, image_base64)
    return


async def handle_sticker_command(
        remote_id: str,
        db_message: Message,
        db: AsyncSession,
):
    message_repo = MessageRepository(db)
    params = parse_params(db_message.content)
    message_to_use = db_message if db_message.media_id else await message_repo.find_by_id(db_message.quoted_message_id)
    if message_to_use.media_id:
        media_repo = MediaRepository(db)
        media = await media_repo.find_by_id(message_to_use.media_id)
        if media.type == "mp4":
            effect = params.get("effect")
            gif_url = await animated_sticker(message_to_use, effect)
            await send_animated_sticker(remote_id, gif_url)
        else:
            is_random = _param_enabled(params.get("random", "false"))
            remove_background = _param_enabled(params.get("no-background", "false"))
            fill = _param_enabled(params.get("fill", "false"))
            webp_base64 = await static_sticker(
                db_message, db, is_random, remove_background, fill
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

        if not quoted_message.media_id:
            await send_message(remote_id, error_message)
            return

        message = quoted_message

    resume = await describe_image_agent(db, user_id, message, group_id)
    await send_message(remote_id, resume)
    return


async def handle_list_images_command(
        remote_id: str, treated_text: Optional[str],
        db: AsyncSession, user_id: Optional[int] = None,
        group_id: Optional[int] = None
):
    if treated_text:
        message = await search_images(treated_text, user_id=user_id, group_id=group_id, db=db)
    else:
        message = await list_images(
            user_id=user_id if not group_id else None,
            group_id=group_id,
            db=db
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
