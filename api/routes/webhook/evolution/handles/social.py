from __future__ import annotations

import asyncio
import base64
import os
import re
import tempfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

import instaloader
import requests

from external.evolution import send_image, send_message, send_video


# ── Twitter ──────────────────────────────────────────────────────────────────

TWITTER_DOMAINS = ("twitter.com", "x.com")

TwitterMediaType = Literal["video", "image"]


@dataclass
class TwitterMediaDownloadResult:
    media_bytes: bytes | None
    media_type: TwitterMediaType | None
    error: str | None

    @property
    def is_success(self) -> bool:
        return self.media_bytes is not None and self.error is None


class InvalidURLError(Exception):
    pass


_TWITTER_REGEX = re.compile(
    rf"https?://(?:www\.)?(?:{'|'.join(map(re.escape, TWITTER_DOMAINS))})/"\
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


async def download_twitter_media(twitter_url: str) -> TwitterMediaDownloadResult:
    try:
        validated_url = _validate_twitter_url(twitter_url)
    except InvalidURLError as e:
        return TwitterMediaDownloadResult(None, None, str(e))

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
                return TwitterMediaDownloadResult(
                    None,
                    None,
                    stderr.decode() or "Erro ao baixar mídia",
                )

            files = os.listdir(tmpdir)
            if not files:
                return TwitterMediaDownloadResult(None, None, "Nenhuma mídia encontrada")

            file_path = os.path.join(tmpdir, files[0])

            with open(file_path, "rb") as f:
                media_bytes = f.read()

            ext = file_path.split(".")[-1].lower()
            if ext in {"mp4", "webm", "mkv"}:
                media_type: TwitterMediaType = "video"
            else:
                media_type = "image"

            return TwitterMediaDownloadResult(media_bytes, media_type, None)

    except Exception as e:
        return TwitterMediaDownloadResult(None, None, f"Erro inesperado: {str(e)}")


# ── Instagram ────────────────────────────────────────────────────────────────

INSTAGRAM_DOMAINS = ("instagram.com",)

InstagramMediaType = Literal["video"]


@dataclass
class InstagramMediaDownloadResult:
    media_bytes: bytes | None
    media_type: InstagramMediaType | None
    error: str | None

    @property
    def is_success(self) -> bool:
        return self.media_bytes is not None and self.error is None


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


def download_instagram_reel(instagram_url: str) -> InstagramMediaDownloadResult:
    try:
        validated_url = _validate_instagram_url(instagram_url)
        shortcode = _extract_shortcode(validated_url)
    except InvalidURLError as e:
        return InstagramMediaDownloadResult(None, None, str(e))
    except Exception:
        return InstagramMediaDownloadResult(None, None, "Erro ao extrair shortcode")

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
            return InstagramMediaDownloadResult(None, None, "Reel não contém vídeo")

        try:
            video_url = post.video_url
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.instagram.com/",
            }

            res = requests.get(video_url, headers=headers, timeout=15)

            if res.status_code == 200 and res.content:
                return InstagramMediaDownloadResult(res.content, "video", None)

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

                return InstagramMediaDownloadResult(media_bytes, "video", None)

            return InstagramMediaDownloadResult(None, None, "Vídeo não encontrado")

    except Exception as e:
        return InstagramMediaDownloadResult(None, None, f"Erro inesperado: {str(e)}")


# ── Handles ──────────────────────────────────────────────────────────────────

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
