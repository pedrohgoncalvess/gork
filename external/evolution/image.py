from typing import Optional

import httpx

from external.evolution.base import evolution_instance_name, evolution_api_key, evolution_api


def extract_quoted_image_bytes(webhook_data: dict) -> Optional[bytes]:
    """
    Extract image bytes from a quoted message in WhatsApp webhook

    Returns:
        bytes: JPEG thumbnail bytes or None if not found
    """
    try:
        context_info = webhook_data['data']['contextInfo']
        quoted_message = context_info.get('quotedMessage', {})
        image_message = quoted_message.get('imageMessage', {})

        jpeg_thumbnail = image_message.get('jpegThumbnail')

        if not jpeg_thumbnail:
            return None

        byte_array = bytearray()
        for i in range(len(jpeg_thumbnail)):
            byte_array.append(jpeg_thumbnail[str(i)])

        return bytes(byte_array)

    except (KeyError, TypeError):
        return None

async def send_sticker(contact_id: str, image_base64: str):
    url = f"{evolution_api}/message/sendSticker/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "sticker": image_base64
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=60)
        return response.json()