from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

TWITTER_DOMAINS = ("twitter.com", "x.com")

MediaType = Literal["video", "image"]


@dataclass
class MediaDownloadResult:
    media_bytes: bytes | None
    media_type: MediaType | None
    error: str | None

    @property
    def is_success(self) -> bool:
        return self.media_bytes is not None and self.error is None


class InvalidURLError(Exception):
    pass


_TWITTER_REGEX = re.compile(
    rf"https?://(?:www\.)?(?:{'|'.join(map(re.escape, TWITTER_DOMAINS))})/"
    r"[\w-]+/status/\d+",
    re.IGNORECASE,
)


def extract_twitter_url(text: str) -> str | None:
    match = _TWITTER_REGEX.search(text)
    return match.group(0) if match else None


def _validate_twitter_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise InvalidURLError("URL deve começar com http:// ou https://")

    domain = parsed.netloc.lower().removeprefix("www.")
    if domain not in TWITTER_DOMAINS:
        raise InvalidURLError("URL deve ser do Twitter/X")

    if not re.match(r"^/[\w-]+/status/\d+", parsed.path):
        raise InvalidURLError("Formato inválido")

    return url


async def download_twitter_media(twitter_url: str) -> MediaDownloadResult:
    try:
        validated_url = _validate_twitter_url(twitter_url)
    except InvalidURLError as e:
        return MediaDownloadResult(None, None, str(e))

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "%(id)s.%(ext)s")

            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-f", "best",
                "-o", output_template,
                "--no-playlist",
                validated_url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            _, stderr = await process.communicate()

            if process.returncode != 0:
                return MediaDownloadResult(
                    None,
                    None,
                    stderr.decode() or "Erro ao baixar mídia",
                )

            files = os.listdir(tmpdir)
            if not files:
                return MediaDownloadResult(None, None, "Nenhuma mídia encontrada")

            file_path = os.path.join(tmpdir, files[0])

            with open(file_path, "rb") as f:
                media_bytes = f.read()

            ext = file_path.split(".")[-1].lower()
            if ext in {"mp4", "webm", "mkv"}:
                media_type: MediaType = "video"
            else:
                media_type = "image"

            return MediaDownloadResult(media_bytes, media_type, None)

    except Exception as e:
        return MediaDownloadResult(None, None, f"Erro inesperado: {str(e)}")