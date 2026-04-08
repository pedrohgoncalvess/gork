from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import instaloader
import requests


INSTAGRAM_DOMAINS = ("instagram.com",)

MediaType = Literal["video"]


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


_INSTAGRAM_REEL_REGEX = re.compile(
    r"https?://(?:www\.)?instagram\.com/reel/[\w-]+",
    re.IGNORECASE,
)


def extract_instagram_url(text: str) -> str | None:
    match = _INSTAGRAM_REEL_REGEX.search(text)
    return match.group(0) if match else None


def _validate_instagram_url(url: str) -> str:
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise InvalidURLError("URL deve começar com http:// ou https://")

    domain = parsed.netloc.lower().removeprefix("www.")
    if domain not in INSTAGRAM_DOMAINS:
        raise InvalidURLError("URL deve ser do Instagram")

    if not re.match(r"^/reel/[\w-]+", parsed.path):
        raise InvalidURLError("Formato inválido (esperado /reel/)")

    return url


def _extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip("/").split("/")
    return parts[1]


def download_instagram_reel(instagram_url: str) -> MediaDownloadResult:
    try:
        validated_url = _validate_instagram_url(instagram_url)
        shortcode = _extract_shortcode(validated_url)
    except InvalidURLError as e:
        return MediaDownloadResult(None, None, str(e))
    except Exception:
        return MediaDownloadResult(None, None, "Erro ao extrair shortcode")

    try:
        L = instaloader.Instaloader(
            download_pictures=False,
            download_videos=True,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
        )

        post = instaloader.Post.from_shortcode(L.context, shortcode)

        if not post.is_video:
            return MediaDownloadResult(None, None, "Reel não contém vídeo")

        try:
            video_url = post.video_url
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.instagram.com/",
            }

            res = requests.get(video_url, headers=headers, timeout=15)

            if res.status_code == 200 and res.content:
                return MediaDownloadResult(res.content, "video", None)

        except Exception:
            pass

        with tempfile.TemporaryDirectory() as tmpdir:
            L.download_post(post, target=tmpdir)

            video_file = None
            for f in os.listdir(tmpdir):
                if f.endswith(".mp4"):
                    video_file = os.path.join(tmpdir, f)
                    break

            if video_file and os.path.exists(video_file):
                with open(video_file, "rb") as f:
                    media_bytes = f.read()

                return MediaDownloadResult(media_bytes, "video", None)

            return MediaDownloadResult(None, None, "Vídeo não encontrado")

    except Exception as e:
        return MediaDownloadResult(None, None, f"Erro inesperado: {str(e)}")