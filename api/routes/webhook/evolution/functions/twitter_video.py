"""Módulo para download de mídia do Twitter/X.

Este módulo fornece funcionalidades para extrair URLs do Twitter/X
e baixar mídia (vídeos e imagens) de posts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from log import logger


# Constantes
TWITTER_DOMAINS = ("twitter.com", "x.com")
TWITSAVE_API_URL = "https://twitsave.com/info"
DEFAULT_TIMEOUT = 30.0
MAX_MEDIA_SIZE_BYTES = 50 * 1024 * 1024  # 50MB

# Media types suportados
MediaType = Literal["video", "image"]


@dataclass
class MediaDownloadResult:
    """Resultado do download de mídia do Twitter/X."""

    media_bytes: bytes | None
    media_type: MediaType | None
    error: str | None

    @property
    def is_success(self) -> bool:
        """Verifica se o download foi bem-sucedido."""
        return self.media_bytes is not None and self.error is None


class TwitterVideoError(Exception):
    """Exceção base para erros relacionados ao Twitter/X."""

    pass


class InvalidURLError(TwitterVideoError):
    """URL do Twitter/X inválido."""

    pass


class MediaNotFoundError(TwitterVideoError):
    """Mídia não encontrada no post."""

    pass


class MediaDownloadError(TwitterVideoError):
    """Erro ao baixar a mídia."""

    pass


def extract_twitter_url(text: str) -> str | None:
    """
    Extrai o primeiro URL válido do Twitter/X de um texto.

    Args:
        text: Texto que pode conter um ou mais URLs do Twitter/X

    Returns:
        URL do Twitter/X encontrado ou None se nenhum for encontrado

    Examples:
        >>> extract_twitter_url("Veja este post: https://x.com/usuario/status/12345")
        "https://x.com/usuario/status/12345"

        >>> extract_twitter_url("Sem URL aqui")
        None
    """
    pattern = rf'https?://(?:{"|".join(TWITTER_DOMAINS)})/[\w-]+/\d+'
    match = re.search(pattern, text)
    return match.group(0) if match else None


def _validate_twitter_url(url: str) -> str:
    """
    Valida e normaliza uma URL do Twitter/X.

    Args:
        url: URL para validar

    Returns:
        URL normalizada

    Raises:
        InvalidURLError: Se a URL for inválida
    """
    parsed = urlparse(url)

    if not parsed.scheme:
        raise InvalidURLError("URL deve ter um esquema (http:// ou https://)")

    if parsed.netloc not in TWITTER_DOMAINS:
        raise InvalidURLError(
            f"URL inválida. Deve ser de {' ou '.join(TWITTER_DOMAINS)}"
        )

    if not parsed.path or parsed.path == "/":
        raise InvalidURLError("URL deve conter um caminho válido (ex: /usuario/status/12345)")

    return url


def _extract_media_url_from_soup(
    soup: BeautifulSoup, media_type: MediaType
) -> str | None:
    """
    Extrai a URL da mídia do HTML parseado.

    Args:
        soup: Objeto BeautifulSoup parseado
        media_type: Tipo de mídia ("video" ou "image")

    Returns:
        URL da mídia ou None se não encontrada
    """
    if media_type == "video":
        video_element = soup.find("a", {"class": "twitsave-btn"})
        return video_element.get("href") if video_element else None

    image_element = soup.find("img", {"class": "twitsave-img"})
    return image_element.get("src") if image_element else None


def _validate_media_size(media_bytes: bytes) -> None:
    """
    Valida o tamanho da mídia baixada.

    Args:
        media_bytes: Bytes da mídia

    Raises:
        MediaDownloadError: Se a mídia for muito grande
    """
    if len(media_bytes) > MAX_MEDIA_SIZE_BYTES:
        size_mb = len(media_bytes) / (1024 * 1024)
        max_mb = MAX_MEDIA_SIZE_BYTES / (1024 * 1024)
        raise MediaDownloadError(
            f"Mídia muito grande: {size_mb:.2f}MB (máximo: {max_mb:.2f}MB)"
        )

    if len(media_bytes) == 0:
        raise MediaDownloadError("Mídia baixada está vazia")


async def _download_media_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    """
    Baixa os bytes de uma URL.

    Args:
        client: Cliente HTTP assíncrono
        url: URL para baixar

    Returns:
        Bytes da mídia

    Raises:
        MediaDownloadError: Se houver erro no download
    """
    try:
        response = await client.get(url)
        response.raise_for_status()
        return response.content
    except httpx.TimeoutException as e:
        raise MediaDownloadError("Timeout ao baixar a mídia") from e
    except httpx.HTTPStatusError as e:
        raise MediaDownloadError(
            f"Erro HTTP ao baixar mídia: {e.response.status_code}"
        ) from e
    except Exception as e:
        raise MediaDownloadError(f"Erro ao baixar mídia: {str(e)}") from e


async def download_twitter_media(twitter_url: str) -> MediaDownloadResult:
    """
    Baixa mídia (vídeo ou imagem) do Twitter/X usando twitsave.com.

    Tenta baixar vídeo primeiro, depois imagem se não encontrar vídeo.

    Args:
        twitter_url: URL do post do Twitter/X

    Returns:
        MediaDownloadResult com os dados do download

    Examples:
        >>> result = await download_twitter_media("https://x.com/usuario/status/12345")
        >>> if result.is_success:
        ...     print(f"Baixou {result.media_type}: {len(result.media_bytes)} bytes")
    """
    try:
        # Valida a URL
        validated_url = _validate_twitter_url(twitter_url)
        await logger.info(
            "TwitterMedia", "Download iniciado", {"url": validated_url}
        )

        # Configura cliente HTTP
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        async with httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            limits=limits,
            follow_redirects=True,
        ) as client:
            # Obtém informações da mídia do twitsave
            try:
                response = await client.post(
                    TWITSAVE_API_URL, data={"url": validated_url}
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    return MediaDownloadResult(
                        None, None, "Erro no servidor twitsave.com. Tente novamente."
                    )
                return MediaDownloadResult(
                    None,
                    None,
                    f"Erro ao conectar com twitsave.com: {e.response.status_code}",
                )

            # Parseia o HTML
            soup = BeautifulSoup(response.text, "html.parser")

            # Tenta baixar vídeo primeiro
            video_url = _extract_media_url_from_soup(soup, "video")
            if video_url:
                try:
                    video_bytes = await _download_media_bytes(client, video_url)
                    _validate_media_size(video_bytes)
                    await logger.info(
                        "TwitterMedia",
                        "Vídeo baixado",
                        {"size": len(video_bytes)},
                    )
                    return MediaDownloadResult(video_bytes, "video", None)
                except MediaDownloadError as e:
                    await logger.warning("TwitterMedia", "Erro vídeo", str(e))
                    # Continua para tentar imagem

            # Tenta baixar imagem
            image_url = _extract_media_url_from_soup(soup, "image")
            if image_url:
                try:
                    image_bytes = await _download_media_bytes(client, image_url)
                    _validate_media_size(image_bytes)
                    await logger.info(
                        "TwitterMedia",
                        "Imagem baixada",
                        {"size": len(image_bytes)},
                    )
                    return MediaDownloadResult(image_bytes, "image", None)
                except MediaDownloadError as e:
                    await logger.warning("TwitterMedia", "Erro imagem", str(e))

            # Se chegou aqui, não encontrou mídia
            return MediaDownloadResult(
                None, None, "Não foi possível encontrar mídia (vídeo ou imagem) no post"
            )

    except InvalidURLError as e:
        return MediaDownloadResult(None, None, str(e))
    except Exception as e:
        await logger.error("TwitterMedia", "Erro inesperado", str(e))
        return MediaDownloadResult(
            None, None, f"Erro ao processar URL: {str(e)}"
        )
