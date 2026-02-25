"""Módulo para envio de imagens, stickers e vídeos via Evolution API.

Este módulo fornece funções para enviar diferentes tipos de mídia
(Imagens, stickers e vídeos) através da Evolution API do WhatsApp.
"""

from __future__ import annotations

from typing import Optional

import httpx
from log import logger

from external.evolution.base import (
    evolution_instance_name,
    evolution_api_key,
    evolution_api,
)


# Constantes
DEFAULT_TIMEOUT = 60.0
DEFAULT_FILENAME_IMAGE = "gork.jpeg"
DEFAULT_FILENAME_VIDEO = "gork.mp4"
MIMETYPE_JPEG = "image/jpeg"
MIMETYPE_MP4 = "video/mp4"


def extract_quoted_image_bytes(webhook_data: dict) -> Optional[bytes]:
    """
    Extrai bytes da imagem de uma mensagem quotada do webhook.

    Args:
        webhook_data: Dados do webhook do WhatsApp

    Returns:
        Bytes da imagem em formato JPEG ou None se não encontrada

    Examples:
        >>> data = {'data': {'contextInfo': {'quotedMessage': {'imageMessage': {'jpegThumbnail': {...}}}}}}
        >>> img_bytes = extract_quoted_image_bytes(data)
    """
    try:
        context_info = webhook_data["data"]["contextInfo"]
        quoted_message = context_info.get("quotedMessage", {})
        image_message = quoted_message.get("imageMessage", {})

        jpeg_thumbnail = image_message.get("jpegThumbnail")

        if not jpeg_thumbnail:
            return None

        # Converte array para bytes
        byte_array = bytearray()
        for i in range(len(jpeg_thumbnail)):
            byte_array.append(jpeg_thumbnail[str(i)])

        return bytes(byte_array)

    except (KeyError, TypeError) as e:
        await logger.warning("EvolutionImage", "Erro ao extrair imagem quotada", str(e))
        return None


async def _send_media_request(
    url: str, payload: dict, timeout: float = DEFAULT_TIMEOUT
) -> dict:
    """
    Envia uma requisição genérica de mídia para a Evolution API.

    Args:
        url: URL completa da API
        payload: Payload da requisição
        timeout: Timeout da requisição em segundos

    Returns:
        Resposta da API em formato JSON

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar com status HTTP diferente de 2xx
    """
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key,
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


async def send_sticker(contact_id: str, image_base64: str) -> dict:
    """
    Envia um sticker (figurinha estática) via WhatsApp.

    Args:
        contact_id: ID do contato (número com sufixo @s.whatsapp.net ou ID do grupo)
        image_base64: Imagem em formato base64 (deve ser WebP para sticker)

    Returns:
        Resposta da API em formato JSON

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar

    Examples:
        >>> result = await send_sticker("5511999999999@s.whatsapp.net", "iVBORw0KGgoAAAANS...")
        >>> # Envio bem-sucedido
    """
    url = f"{evolution_api}/message/sendSticker/{evolution_instance_name}"

    payload = {"number": contact_id, "sticker": image_base64}

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error("EvolutionSticker", "Erro ao enviar sticker", str(e))
        raise


async def send_animated_sticker(contact_id: str, sticker_url: str) -> dict:
    """
    Envia um sticker animado via WhatsApp.

    Args:
        contact_id: ID do contato (número com sufixo @s.whatsapp.net ou ID do grupo)
        sticker_url: URL do sticker animado

    Returns:
        Resposta da API em formato JSON

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar

    Examples:
        >>> result = await send_animated_sticker("5511999999999@s.whatsapp.net", "https://...")
    """
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
    """
    Envia uma imagem via WhatsApp.

    Args:
        contact_id: ID do contato (número com sufixo @s.whatsapp.net ou ID do grupo)
        image_base64: Imagem em formato base64
        filename: Nome do arquivo (padrão: "gork.jpeg")
        caption: Legenda da imagem (vazia por padrão)

    Returns:
        Resposta da API em formato JSON

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar

    Examples:
        >>> result = await send_image(
        ...     "5511999999999@s.whatsapp.net",
        ...     "/9j/4AAQSkZJRg...",
        ...     caption="Minha imagem"
        ... )
    """
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
    filename: str = DEFAULT_FILENAME_VIDEO,
    caption: str = "",
) -> dict:
    """
    Envia um vídeo via WhatsApp.

    Args:
        contact_id: ID do contato (número com sufixo @s.whatsapp.net ou ID do grupo)
        video_base64: Vídeo em formato base64
        quoted_message_id: ID da mensagem para resposta (opcional)
        filename: Nome do arquivo (padrão: "gork.mp4")
        caption: Legenda do vídeo (vazia por padrão)

    Returns:
        Resposta da API em formato JSON

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar

    Examples:
        >>> result = await send_video(
        ...     "5511999999999@s.whatsapp.net",
        ...     "AAAAIGZ0eXBpc29tAAACAg...",
        ...     quoted_message_id="msg_123",
        ...     caption="Meu vídeo"
        ... )
    """
    url = f"{evolution_api}/message/sendMedia/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "mediatype": "video",
        "fileName": filename,
        "media": video_base64,
        "mimetype": MIMETYPE_MP4,
        "caption": caption,
    }

    # Adiciona quoted message se fornecido
    if quoted_message_id:
        payload["quoted"] = {"key": {"id": quoted_message_id}}

    try:
        return await _send_media_request(url, payload)
    except Exception as e:
        await logger.error("EvolutionVideo", "Erro ao enviar vídeo", str(e))
        raise


async def get_profile_info(number: str) -> dict:
    """
    Obtém informações do perfil de um número do WhatsApp.

    Args:
        number: Número do WhatsApp (apenas dígitos, com código do país)

    Returns:
        Dicionário com informações do perfil

    Raises:
        httpx.HTTPStatusError: Se a requisição falhar

    Examples:
        >>> info = await get_profile_info("5511999999999")
        >>> print(info["pushName"])
    """
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
