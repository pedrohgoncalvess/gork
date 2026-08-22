from __future__ import annotations

import asyncio
import base64
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

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
