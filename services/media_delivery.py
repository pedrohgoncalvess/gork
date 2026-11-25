"""Delivery of a selected, scope-checked library or conversation attachment."""
import mimetypes

from external.waha import send_audio, send_image, send_video, send_sticker, send_animated_sticker
from s3 import S3Client
from services.media_search import resolve_media


async def deliver_media(db, *, remote_id, user_id, group_id, action_type, parameters, quoted_message_id=None):
    media = await resolve_media(
        db, user_id=user_id, group_id=group_id, media_id=parameters.get("media_id"),
        media_source=parameters.get("media_source", "library"), message_id=parameters.get("message_id"),
    )
    expected = {"send_audio": {"audio"}, "send_image": {"image", "sticker"}, "send_video": {"video"}}
    if not media or media.type not in expected.get(action_type, set()):
        raise ValueError("Media unavailable or type mismatch")
    storage = S3Client()
    await storage.connect()
    data = await storage.get_image_base64(media.bucket, media.path)
    if not data:
        raise ValueError("Empty media")
    if media.type == "audio":
        return await send_audio(remote_id, data, quoted_message_id)
    if media.type == "video":
        return await send_video(remote_id, data, quoted_message_id)
    if media.type == "sticker":
        from agents.describe_video.agent import is_animation
        import base64
        sender = send_animated_sticker if is_animation(base64.b64decode(data)) else send_sticker
        return await sender(remote_id, data)
    return await send_image(remote_id, data, filename=media.name or "image.jpg",
                            mimetype=mimetypes.guess_type(media.path)[0] or "image/jpeg")
