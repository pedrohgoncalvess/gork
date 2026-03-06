from __future__ import annotations

from typing import Optional

import httpx
from log import logger

from external.evolution.base import (
    evolution_instance_name,
    evolution_api_key,
    evolution_api,
)


DEFAULT_TIMEOUT = 60.0
DEFAULT_FILENAME_IMAGE = "gork.jpeg"
DEFAULT_FILENAME_VIDEO = "gork.mp4"
MIMETYPE_JPEG = "image/jpeg"
MIMETYPE_MP4 = "video/mp4"

async def extract_quoted_image_bytes(webhook_data: dict) -> Optional[bytes]:
    try:
        context_info = webhook_data["data"]["contextInfo"]
        quoted_message = context_info.get("quotedMessage", {})
        image_message = quoted_message.get("imageMessage", {})

        jpeg_thumbnail = image_message.get("jpegThumbnail")

        if not jpeg_thumbnail:
            return None

        byte_array = bytearray()
        for i in range(len(jpeg_thumbnail)):
            byte_array.append(jpeg_thumbnail[str(i)])

        return bytes(byte_array)

    except (KeyError, TypeError) as e:
        await logger.error("EvolutionImage", "Erro ao extrair imagem quotada", str(e))
        return None


async def _send_media_request(
    url: str, payload: dict, timeout: float = DEFAULT_TIMEOUT
) -> dict:
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_sticker(contact_id: str, image_base64: str) -> dict:
    url = f"{evolution_api}/message/sendSticker/{evolution_instance_name}"

    payload = {"number": contact_id, "sticker": image_base64}

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error("EvolutionSticker", "Erro ao enviar sticker", str(e))
        raise


async def send_animated_sticker(contact_id: str, sticker_url: str) -> dict:
    url = f"{evolution_api}/message/sendSticker/{evolution_instance_name}"

    payload = {"number": contact_id, "sticker": sticker_url}

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error(
            "EvolutionSticker", "Erro ao enviar sticker animado", str(e)
        )
        raise


async def send_image(
    contact_id: str,
    image_base64: str,
    filename: str = DEFAULT_FILENAME_IMAGE,
    caption: str = "",
) -> dict:
    url = f"{evolution_api}/message/sendMedia/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "mediatype": "image",
        "fileName": filename,
        "media": image_base64,
        "mimetype": MIMETYPE_JPEG,
        "caption": caption,
    }

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error("EvolutionImage", "Erro ao enviar imagem", str(e))
        raise


async def send_video(
    contact_id: str,
    video_base64: str,
    quoted_message_id: Optional[str] = None,
    caption: str = "",
) -> dict:
    url = f"{evolution_api}/message/sendMedia/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "mediatype": "video",
        "media": video_base64,
        "mimetype": MIMETYPE_MP4,
        "caption": caption,
    }

    if quoted_message_id:
        payload["quoted"] = {"key": {"id": quoted_message_id}}

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error("EvolutionVideo", f"Erro ao enviar vídeo. Payload: {payload}", str(e))
        raise


async def get_profile_info(number: str) -> dict:
    url = f"{evolution_api}/chat/fetchProfile/{evolution_instance_name}"

    payload = {"number": number}

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        await logger.error("EvolutionProfile", "Erro ao obter perfil", str(e))
        raise
