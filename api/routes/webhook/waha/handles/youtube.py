import asyncio
import base64
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from external.waha import send_message, send_video
from log import logger


_URL_PATTERN = re.compile(
    r"""(?::url=(?P<quote>["'])?)?(?P<url>https?://[^\s<>"'`]+)(?(quote)(?P=quote))""",
    re.IGNORECASE,
)
_VIDEO_ID = re.compile(r"[a-zA-Z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_MAX_VIDEO_BYTES = 16 * 1024 * 1024


class YouTubeDownloadError(Exception):
    pass


def _normalize_youtube_url(url: str) -> str | None:
    try:
        parsed = urlsplit(url.rstrip(".,;!?)]}*"))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None

    path = parsed.path.rstrip("/")
    if parsed.netloc.lower() == "youtu.be":
        video_id = path.removeprefix("/")
    elif parsed.netloc.lower() in _YOUTUBE_HOSTS:
        if path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif path.startswith("/shorts/"):
            video_id = path.removeprefix("/shorts/")
        else:
            return None
    else:
        return None
    if _VIDEO_ID.fullmatch(video_id):
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def extract_youtube_url(text: str) -> str | None:
    for match in _URL_PATTERN.finditer(text):
        url = _normalize_youtube_url(match["url"])
        if url:
            return url
    return None


def remove_youtube_urls(text: str) -> str:
    return _URL_PATTERN.sub(
        lambda match: " " if _normalize_youtube_url(match["url"]) else match[0],
        text,
    )


def _download_youtube_video(url: str) -> bytes:
    with TemporaryDirectory() as temp_dir:
        output = Path(temp_dir) / "video.mp4"
        process = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "--ignore-config", "--no-playlist", "--no-progress", "--no-warnings",
                "--socket-timeout", "10", "--retries", "1",
                "--max-filesize", str(_MAX_VIDEO_BYTES),
                "--format",
                "(bv[vcodec^=avc1]+ba[acodec^=mp4a])"
                "/b[ext=mp4][vcodec^=avc1][acodec^=mp4a]",
                "--format-sort", "res:720",
                "--merge-output-format", "mp4",
                "--output", str(output.with_suffix(".%(ext)s")),
                "--", url,
            ],
            capture_output=True,
            timeout=60,
        )
        if b"max-filesize" in process.stdout or (
            output.is_file() and output.stat().st_size > _MAX_VIDEO_BYTES
        ):
            raise YouTubeDownloadError("O vídeo do YouTube excede o limite de 16 MiB.")
        if process.returncode or not output.is_file():
            error = process.stderr.decode("utf-8", errors="replace").strip()
            raise YouTubeDownloadError(
                "Não consegui baixar esse vídeo do YouTube. Verifique se ele está disponível."
            ) from RuntimeError(error)
        return output.read_bytes()


async def download_youtube_video(url: str) -> bytes:
    normalized_url = _normalize_youtube_url(url)
    if not normalized_url:
        raise YouTubeDownloadError("Envie um link válido de vídeo ou Short do YouTube.")
    try:
        return await asyncio.to_thread(_download_youtube_video, normalized_url)
    except YouTubeDownloadError as error:
        if error.__cause__:
            await logger.error("YouTube", "DownloadFailed", str(error.__cause__))
        raise
    except subprocess.TimeoutExpired:
        raise YouTubeDownloadError("O download do vídeo do YouTube demorou demais.") from None
    except OSError as error:
        await logger.error("YouTube", "DownloadFailed", str(error))
        raise YouTubeDownloadError("Não consegui baixar o vídeo do YouTube. Tente novamente.") from error


async def handle_youtube_command(remote_id: str, conversation: str, message_id: str) -> None:
    url = extract_youtube_url(conversation)
    if not url:
        await send_message(remote_id, "Use !youtube <link de vídeo ou Short do YouTube>.", message_id)
        return
    try:
        video = await download_youtube_video(url)
    except YouTubeDownloadError as error:
        await send_message(remote_id, str(error), message_id)
        return
    await send_video(remote_id, base64.b64encode(video).decode("ascii"), message_id)
