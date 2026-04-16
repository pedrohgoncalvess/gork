import base64
from external.evolution import send_message, send_video, send_image
from api.routes.webhook.evolution.functions.instagram_video import extract_instagram_url, download_instagram_reel
from api.routes.webhook.evolution.functions import extract_twitter_url, download_twitter_media


async def handle_twitter_command(
    remote_id: str,
    conversation: str,
    message_id: str,
):
    twitter_url = extract_twitter_url(conversation)

    if not twitter_url:
        await send_message(
            remote_id,
            "❌ Envie um link válido do Twitter/X.\n\n"
            "`!twitter https://x.com/usuario/status/12345`",
            message_id,
        )
        return

    result = await download_twitter_media(twitter_url)

    if not result.is_success:
        await send_message(remote_id, f"❌ {result.error}", message_id)
        return

    media_base64 = base64.b64encode(result.media_bytes).decode()

    if result.media_type == "video":
        await send_video(remote_id, media_base64, message_id)
    else:
        await send_image(remote_id, media_base64)


async def handle_instagram_command(
    remote_id: str,
    conversation: str,
    message_id: str,
):
    instagram_url = extract_instagram_url(conversation)

    if not instagram_url:
        await send_message(
            remote_id,
            "❌ Envie um link de reel do Instagram/X.\n\n"
            "`!instagram https://www.instagram.com/reel/XXXXXX",
            message_id,
        )
        return

    result = download_instagram_reel(instagram_url)

    if not result.is_success:
        await send_message(remote_id, f"❌ {result.error}", message_id)
        return

    media_base64 = base64.b64encode(result.media_bytes).decode()

    await send_video(remote_id, media_base64, message_id)
