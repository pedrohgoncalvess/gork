import asyncio
import math
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from api.routes.webhook.waha.handles.image.sticker_animated import (
    VIDEO_CUT_MAX_DURATION,
    _parse_cut_range,
)
from database.operations.content import MediaRepository, MessageRepository
from external.waha.identifiers import get_reference
from external.waha.sound_sticker import send_sound_sticker
from services.media_tags import pending_media_tag


class StickerAudioUnavailable(ValueError):
    pass


def sticker_cut(params, track: str):
    return params.get(f"cut-{track}", params.get("cut"))


def _webp_duration(webp: bytes) -> float | None:
    with Image.open(BytesIO(webp)) as image:
        if not image.is_animated:
            return None
        milliseconds = 0
        for frame in range(image.n_frames):
            image.seek(frame)
            image.load()
            milliseconds += image.info.get("duration", 0)
    return min(milliseconds / 1000, VIDEO_CUT_MAX_DURATION)


def _sound_duration_limit(webp: bytes, video: bytes | None, cut_spec) -> float:
    rendered = _webp_duration(webp)
    if rendered is not None:
        return rendered
    if video is None:
        return VIDEO_CUT_MAX_DURATION
    # A video whose frames are identical can be encoded as a single WebP frame.
    # In that case the image itself carries no playback duration.
    start, cut_duration = _parse_cut_range(cut_spec) or (0, VIDEO_CUT_MAX_DURATION)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "video"
        path.write_bytes(video)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=duration:format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, timeout=10,
        )
    for line in probe.stdout.decode().splitlines():
        try:
            duration = float(line)
        except ValueError:
            continue
        if math.isfinite(duration):
            return min(cut_duration, max(0, duration - start))
    return cut_duration


def extract_sticker_audio(source: bytes, cut_spec, limit: float) -> tuple[bytes, float]:
    cut = _parse_cut_range(cut_spec)
    if cut_spec is not None and (not cut or not all(map(math.isfinite, cut))):
        raise StickerAudioUnavailable("Recorte de áudio inválido.")
    start, duration = cut or (0, VIDEO_CUT_MAX_DURATION)
    duration = min(duration, limit)
    if duration <= 0:
        raise StickerAudioUnavailable("Não encontrei áudio no trecho selecionado.")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "source"
        path.write_bytes(source)
        # PCM keeps the exact duration and lets us detect a missing or empty track.
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(path),
             "-t", str(duration), "-map", "0:a:0", "-ac", "1", "-ar", "48000",
             "-f", "s16le", "pipe:1"],
            capture_output=True, timeout=30,
        )
    if result.returncode or not result.stdout:
        raise StickerAudioUnavailable("Não encontrei áudio no trecho selecionado.")
    encoded = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-f", "s16le", "-ac", "1", "-ar", "48000",
         "-i", "pipe:0", "-c:a", "libopus", "-f", "ogg", "pipe:1"],
        input=result.stdout, capture_output=True, check=True, timeout=15,
    )
    return encoded.stdout, len(result.stdout) / 96000


def _prepare_sticker_audio(source, webp, video, params):
    return extract_sticker_audio(
        source, sticker_cut(params, "audio"),
        _sound_duration_limit(webp, video, sticker_cut(params, "video")),
    )


async def deliver_sound_sticker(destination, message, db, webp, video, params, load_media):
    async with pending_media_tag(message.user_id, "audio") as tag:
        source = video
        if tag:
            tagged_message = await MessageRepository(db).find_by_message_id(tag)
            media = None
            if tagged_message and tagged_message.media_id:
                media = await MediaRepository(db).find_by_id(tagged_message.media_id)
            source = await load_media(tagged_message or message, media, tag)
        if not source:
            raise StickerAudioUnavailable("Use um vídeo com áudio ou marque um áudio com !tag.")
        audio, duration = await asyncio.to_thread(_prepare_sticker_audio, source, webp, video, params)
        reference = await get_reference(message.message_id)
        # Use the actual chat address supplied by WAHA (including @lid in DMs).
        chat = reference["chat_id"] if reference else destination
        await send_sound_sticker(chat, webp, audio, duration)
