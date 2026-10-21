import base64

import httpx

from external.waha.base import chat_id, request, segment, waha_session
from external.waha.media import download_media, send_file


async def extract_quoted_image_bytes(webhook_data: dict) -> bytes | None:
    context = webhook_data.get("data", {}).get("contextInfo") or {}
    if context.get("stanzaId") and context.get("quotedMessage", {}).get("imageMessage"):
        value, _ = await download_media(context["stanzaId"])
        return base64.b64decode(value)
    return None


async def send_sticker(contact_id: str, image_base64: str) -> dict:
    return await send_file(contact_id, "/api/sendSticker", image_base64,
                           "gork.webp", "image/webp")


async def send_animated_sticker(contact_id: str, sticker_url: str) -> dict:
    return await send_sticker(contact_id, sticker_url)


async def send_image(contact_id: str, image_base64: str, filename: str = "gork.jpeg",
                     caption: str = "", mimetype: str = "image/jpeg") -> dict:
    return await send_file(contact_id, "/api/sendImage", image_base64, filename,
                           mimetype, caption=caption)


async def send_video(contact_id: str, video_base64: str, quoted_message_id: str | None = None,
                     caption: str = "") -> dict:
    return await send_file(contact_id, "/api/sendVideo", video_base64, "gork.mp4",
                           "video/mp4", quoted_message_id, caption=caption)


async def get_profile_info(number: str) -> dict:
    if not number:
        return {"picture": None}
    try:
        result = await request("GET", "/api/contacts/profile-picture", params={
            "session": waha_session, "contactId": chat_id(number), "refresh": "false",
        })
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            return {"picture": None}
        raise
    return {**result, "picture": result.get("profilePictureURL") or result.get("url")}
