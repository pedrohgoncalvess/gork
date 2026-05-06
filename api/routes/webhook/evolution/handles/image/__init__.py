from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution.describe_image import describe_image_agent
from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.gallery import list_images, search_images
from api.routes.webhook.evolution.handles.image.generate import generate_image
from api.routes.webhook.evolution.handles.image.picture import get_pictures
from api.routes.webhook.evolution.handles.image.sticker_animated import animated_sticker
from api.routes.webhook.evolution.handles.image.sticker_static import static_sticker
from database.models.content import Message
from database.operations.content import MessageRepository
from external.evolution import send_animated_sticker, send_image, send_message, send_sticker
from services import parse_params


def _param_enabled(value) -> bool:
    return str(value).lower() in ["true", "t", "1", "yes", "y"]


async def handle_image_command(
        remote_id: str,
        user_id: int,
        db_message: Message,
        context: dict,
        group_id: Optional[int] = None
):
    treated_text = clean_text(db_message.content, False)
    image_base64, error = await generate_image(user_id, treated_text, context, db_message, group_id)
    if error:
        await send_message(remote_id, image_base64)
        return
    await send_image(remote_id, image_base64)
    return


async def handle_sticker_command(
        remote_id: str,
        db_message: Message,
        db: AsyncSession,
        message_context: dict
):
    medias = message_context.keys()
    treated_text = clean_text(db_message.content)
    params = parse_params(db_message.content)
    if "video_message" in medias or "video_quote" in medias or "sticker_quote" in medias:
        effect = params.get("effect")
        if "video_quote" in medias:
            message_id = message_context.get("video_quote")
        elif "video_message" in medias:
            message_id = message_context.get("video_message")
        else:
            message_id = message_context.get("sticker_quote")
        gif_url = await animated_sticker(message_id, treated_text, effect)
        await send_animated_sticker(remote_id, gif_url)
    else:
        is_random = _param_enabled(params.get("random", "false"))
        remove_background = _param_enabled(params.get("no-background", "false"))
        fill = _param_enabled(params.get("fill", "false"))
        webp_base64 = await static_sticker(
            db_message, treated_text, db,
            message_context, is_random, remove_background, fill
        )
        await send_sticker(remote_id, webp_base64)


async def handle_describe_image_command(
        remote_id: str,
        user_id: int,
        medias: dict[str, str],
        db: AsyncSession,
        group_id: Optional[int] = None
):
    target_message_id = medias.get("image_message") or medias.get("image_quote")
    if not target_message_id:
        await send_message(remote_id, "Nao encontrei uma imagem para descrever.")
        return

    if str(target_message_id).isdigit():
        message_repo = MessageRepository(db)
        target_message = await message_repo.find_by_id(int(target_message_id))
        if target_message:
            target_message_id = target_message.message_id

    resume = await describe_image_agent(db, user_id, str(target_message_id), group_id)
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
    context: dict[str, any],
    db: AsyncSession,
):
    message_id = context.get("quoted_message")
    mentions = context.get("mentions")

    if len(mentions) == 0:
        await send_message(remote_id, "Ninguem foi mencionado.", message_id)

    pictures_for_send = await get_pictures(context, db)

    for type_, picture in pictures_for_send:
        if type_:
            await send_image(remote_id, picture)
        else:
            await send_message(remote_id, picture, message_id)

    return
