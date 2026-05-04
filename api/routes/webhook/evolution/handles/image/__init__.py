from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.generate import generate_image
from api.routes.webhook.evolution.handles.image.gallery import list_images, search_images
from api.routes.webhook.evolution.handles.image.picture import get_pictures
from api.routes.webhook.evolution.handles.image.sticker_static import static_sticker
from api.routes.webhook.evolution.handles.image.sticker_animated import animated_sticker
from external.evolution import send_message, send_image, send_sticker, send_animated_sticker, download_media
from services import describe_image, parse_params


async def handle_image_command(
        remote_id: str,
        user_id: int,
        raw_text: str,
        body: dict,
        group_id: Optional[int] = None
):
    treated_text = clean_text(raw_text, False)
    image_base64, error = await generate_image(user_id, treated_text, body, group_id)
    if error:
        await send_message(remote_id, image_base64)
        return
    await send_image(remote_id, image_base64)
    return


async def handle_sticker_command(
        remote_id: str,
        body: dict,
        treated_text: str,
        message: str,
        db: AsyncSession,
        message_context: dict
):
    medias = message_context.keys()
    params = parse_params(message)
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
        is_random = True if params.get("random", "f") == "t" else False
        remove_background = True if params.get("no-background", "f") == "t" else False
        webp_base64 = await static_sticker(
            body, treated_text, db,
            message_context, is_random, remove_background
        )
        await send_sticker(remote_id, webp_base64)


async def handle_describe_image_command(
        remote_id: str,
        user_id: int,
        treated_text: str,
        medias: dict[str, str],
        group_id: Optional[int] = None
):
    if "image_message" in medias.keys():
        image_base64, _ = await download_media(medias["image_message"])
    else:
        image_base64, _ = await download_media(medias["image_quote"])

    resume = await describe_image(user_id, treated_text, image_base64, group_id)
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
