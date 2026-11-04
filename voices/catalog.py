import asyncio
from dataclasses import dataclass
import math
from pathlib import Path
import re
import subprocess
import unicodedata

import yaml

from database import PgConnection
from database.operations.content.voice import VoiceRepository
from log import logger
from utils import project_root


VOICES_ROOT = Path(project_root) / "voices"
SUPPORTED_EXTENSIONS = {".mp4", ".m4a", ".mp3", ".wav", ".ogg", ".webm", ".flac", ".aac"}


class VoiceSelectionError(ValueError):
    """A user-selected voice is missing or no longer usable."""


@dataclass(frozen=True)
class AvailableVoice:
    name: str
    display_name: str


def voice_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def reference_path(relative_path: str, root: Path | None = None) -> Path:
    root = (root or VOICES_ROOT).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("Voice references must be supported media files inside voices/.")
    if not path.is_file():
        raise ValueError(f"Voice reference not found: {relative_path}")
    return path


def extract_reference(path: Path, start: float = 0, duration: float = 180) -> bytes:
    """Convert even MP4 references to bounded mono WAV without blocking asyncio."""
    result = subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(start), "-i", str(path), "-t", str(duration),
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "24000",
        "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
    ], capture_output=True, timeout=60, check=False)
    if result.returncode or len(result.stdout) < 4800 or len(result.stdout) > 15 * 1024 * 1024:
        raise ValueError(f"Cannot extract usable reference audio from {path.name}.")
    return result.stdout


async def init_voices(root: Path | None = None) -> int:
    root = root or VOICES_ROOT
    metadata = root / "metadata.yaml"
    if not metadata.is_file():
        raise ValueError("voices/metadata.yaml not found.")
    config = yaml.safe_load(metadata.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("voices"), list):
        raise ValueError("Voice metadata must contain a voices list.")
    entries = []
    names = set()
    for item in config["voices"]:
        if not isinstance(item, dict):
            raise ValueError("Each voice entry must be a mapping.")
        name = voice_name(str(item.get("name", "")))
        if not name or name in names:
            raise ValueError(f"Empty or duplicate voice name: {name}")
        names.add(name)
        if item.get("enabled", True) is False:
            continue
        start = float(item.get("start_seconds", 0))
        duration = float(item.get("duration_seconds", 180))
        if not math.isfinite(start) or start < 0 or not math.isfinite(duration) or not 0 < duration <= 180:
            raise ValueError(f"Invalid reference interval for {name}.")
        language = item.get("language", "pt")
        if language not in {"pt", "en", "es"}:
            raise ValueError(f"Unsupported reference language for {name}.")
        try:
            path = reference_path(item["path"], root)
            # A missing audio track, empty clip or corrupt file must not become
            # an advertised voice. Extract once at startup to validate it.
            await asyncio.to_thread(extract_reference, path, start, duration)
        except (KeyError, ValueError, OSError, subprocess.TimeoutExpired):
            await logger.error("Voices", "Initialization", f"Unavailable reference for {name}.")
            continue
        entries.append({
            "name": name, "display_name": str(item.get("display_name") or name),
            "file_path": path.relative_to(root.resolve()).as_posix(),
            "language": language, "start_seconds": start, "duration_seconds": duration,
            "source_url": item.get("source_url"),
        })
    async with PgConnection() as db:
        await VoiceRepository(db).sync(entries)
    await logger.info("Voices", "Initialization", f"Registered {len(entries)} available voices.")
    return len(entries)


async def available_voices() -> list[AvailableVoice]:
    async with PgConnection() as db:
        rows = await VoiceRepository(db).available()
        # PgConnection rolls back read transactions on close. Copy values before
        # that expires ORM objects so help never reads detached database rows.
        return [AvailableVoice(row.name, row.display_name) for row in rows]


if __name__ == "__main__":
    asyncio.run(init_voices())
