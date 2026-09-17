from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from io import BytesIO
from typing import Literal
from urllib.parse import urlparse

import httpx
from PIL import Image

from external.evolution import send_image, send_message, send_video


# ── Twitter ──────────────────────────────────────────────────────────────────

TWITTER_DOMAINS = ("twitter.com", "x.com")

TwitterMediaType = Literal["video", "image"]


@dataclass
class TwitterMediaDownloadResult:
    media_bytes: bytes | None
    media_type: TwitterMediaType | None
    error: str | None
    text: str | None = None

    @property
    def is_success(self) -> bool:
        return self.media_bytes is not None and self.error is None


class InvalidURLError(Exception):
    pass


_TWITTER_REGEX = re.compile(
    rf"https?://(?:www\.)?(?:{'|'.join(map(re.escape, TWITTER_DOMAINS))})/"\
    r"[\w-]+/status/\d+(?:[/?#][^\s]*)?",
    re.IGNORECASE,
)


def normalize_twitter_url(url: str) -> str:
    parsed = urlparse(str(url).strip())
    return parsed._replace(query="", fragment="").geturl()


def extract_twitter_url(text: str) -> str | None:
    match = _TWITTER_REGEX.search(text)
    return normalize_twitter_url(match.group(0)) if match else None


def remove_twitter_urls(text: str) -> str:
    return _TWITTER_REGEX.sub("", text or "").strip()


def _validate_twitter_url(url: str) -> str:
    normalized_url = normalize_twitter_url(url)
    parsed = urlparse(normalized_url)

    if parsed.scheme not in {"http", "https"}:
        raise InvalidURLError("URL deve começar com http:// ou https://")

    domain = parsed.netloc.lower().removeprefix("www.")
    if domain not in TWITTER_DOMAINS:
        raise InvalidURLError("URL deve ser do Twitter/X")

    if not re.match(r"^/[\w-]+/status/\d+", parsed.path):
        raise InvalidURLError("Formato inválido")

    return normalized_url


async def download_twitter_media(twitter_url: str) -> TwitterMediaDownloadResult:
    try:
        validated_url = _validate_twitter_url(twitter_url)
    except InvalidURLError as e:
        return TwitterMediaDownloadResult(None, None, str(e))

    tweet_id = urlparse(validated_url).path.rstrip("/").split("/")[-1]
    status_task = asyncio.create_task(_fetch_twitter_status(tweet_id))
    video_bytes, video_text, video_error = await _download_twitter_video(validated_url)

    try:
        status = await status_task
    except Exception:
        status = None

    tweet_text = _extract_twitter_text(status) or video_text
    if video_bytes:
        return TwitterMediaDownloadResult(video_bytes, "video", None, tweet_text)

    photo_url = _find_twitter_photo_url(status)
    if photo_url:
        photo_bytes, photo_error = await _download_twitter_photo(photo_url)
        if photo_bytes:
            return TwitterMediaDownloadResult(photo_bytes, "image", None, tweet_text)
        return TwitterMediaDownloadResult(None, None, photo_error, tweet_text)

    return TwitterMediaDownloadResult(
        None,
        None,
        video_error or "Nenhuma mídia encontrada",
        tweet_text,
    )


async def _download_twitter_video(url: str) -> tuple[bytes | None, str | None, str | None]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "%(id)s.%(ext)s")
            process = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "-f",
                "best[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
                "--write-info-json",
                "-o",
                output_template,
                "--no-playlist",
                url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()

            info_text = None
            info_files = [name for name in os.listdir(tmpdir) if name.endswith(".info.json")]
            if info_files:
                try:
                    with open(os.path.join(tmpdir, info_files[0]), encoding="utf-8") as file:
                        info_text = json.load(file).get("description")
                except (OSError, ValueError, AttributeError):
                    pass

            video_extensions = {"mp4", "webm", "mkv", "mov"}
            video_files = [
                name
                for name in os.listdir(tmpdir)
                if name.rsplit(".", 1)[-1].lower() in video_extensions
            ]
            if process.returncode == 0 and video_files:
                with open(os.path.join(tmpdir, video_files[0]), "rb") as file:
                    return file.read(), info_text, None

            error = stderr.decode(errors="replace").strip()
            return None, info_text, error or "Nenhum vídeo encontrado"
    except FileNotFoundError:
        return None, None, "yt-dlp não está instalado"
    except Exception as error:
        return None, None, f"Erro ao baixar vídeo ({type(error).__name__})"


async def _fetch_twitter_status(tweet_id: str) -> dict | None:
    def fetch() -> dict | None:
        # Reuse yt-dlp's signed syndication request. Its public extraction result
        # intentionally omits photos, while the normalized status retains them.
        from yt_dlp import YoutubeDL
        from yt_dlp.extractor.twitter import TwitterIE

        with YoutubeDL({"quiet": True, "no_warnings": True}) as downloader:
            extractor = TwitterIE(downloader)
            extractor._selected_api = "syndication"
            return extractor._extract_status(tweet_id)

    return await asyncio.to_thread(fetch)


def _twitter_media(status: dict | None) -> list[dict]:
    if not status:
        return []

    media = []
    for post in (status, status.get("quoted_status")):
        if not isinstance(post, dict):
            continue
        entities = post.get("extended_entities") or {}
        for item in entities.get("media") or []:
            if isinstance(item, dict):
                media.append(item)
    return media


def _extract_twitter_text(status: dict | None) -> str | None:
    if not status:
        return None

    text = status.get("full_text") or status.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    for media in _twitter_media(status):
        media_link = media.get("url")
        if media_link:
            text = text.replace(media_link, "")
    return re.sub(r"\s+", " ", text).strip() or None


def _find_twitter_photo_url(status: dict | None) -> str | None:
    for media in _twitter_media(status):
        if media.get("type") != "photo":
            continue
        return media.get("media_url_https") or media.get("media_url")
    return None


async def _download_twitter_photo(url: str) -> tuple[bytes | None, str | None]:
    separator = "&" if "?" in url else "?"
    original_url = f"{url}{separator}name=orig"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(original_url)
            response.raise_for_status()
        image_bytes = response.content
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
        return image_bytes, None
    except Exception as error:
        return None, f"Não foi possível baixar a imagem ({type(error).__name__})"


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


def download_instagram_reel(instagram_url: str) -> InstagramMediaDownloadResult:
    try:
        validated_url = _validate_instagram_url(instagram_url)
    except InvalidURLError as e:
        return InstagramMediaDownloadResult(None, None, str(e))

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_template = os.path.join(tmpdir, "reel.%(ext)s")
            command = [
                "yt-dlp",
                "--no-playlist",
                "--no-warnings",
                "-f",
                "best[ext=mp4]/best",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
            ]

            cookies_file = os.getenv("INSTAGRAM_COOKIES_FILE")
            if cookies_file:
                if not os.path.isfile(cookies_file):
                    return InstagramMediaDownloadResult(
                        None,
                        None,
                        "Arquivo de cookies do Instagram não encontrado",
                    )
                command.extend(["--cookies", cookies_file])

            command.append(validated_url)
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

            if process.returncode != 0:
                error = process.stderr.strip()
                normalized_error = error.lower()
                if any(
                    message in normalized_error
                    for message in (
                        "login required",
                        "empty media response",
                        "use --cookies",
                    )
                ):
                    if cookies_file:
                        error = "Instagram exige uma sessão válida; atualize os cookies"
                    else:
                        error = (
                            "Instagram bloqueou o acesso anônimo; "
                            "configure INSTAGRAM_COOKIES_FILE"
                        )
                elif "not available" in normalized_error or "private" in normalized_error:
                    error = "Reel indisponível ou privado"
                else:
                    error = "Não foi possível baixar o reel"

                return InstagramMediaDownloadResult(None, None, error)

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

    except subprocess.TimeoutExpired:
        return InstagramMediaDownloadResult(None, None, "Tempo limite ao baixar o reel")
    except FileNotFoundError:
        return InstagramMediaDownloadResult(None, None, "yt-dlp não está instalado")

    except Exception as e:
        return InstagramMediaDownloadResult(
            None,
            None,
            f"Não foi possível baixar o reel ({type(e).__name__})",
        )


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
            "❌ Envie um link de reel do Instagram.\n\n"
            "`!instagram https://www.instagram.com/reel/XXXXXX`",
            message_id,
        )
        return

    result = await asyncio.to_thread(download_instagram_reel, instagram_url)

    if not result.is_success:
        await send_message(remote_id, f"❌ {result.error}", message_id)
        return

    media_base64 = base64.b64encode(result.media_bytes).decode()

    await send_video(remote_id, media_base64, message_id)
