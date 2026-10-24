"""Identify input containers without decoding or transcoding speech locally."""
import json
from pathlib import PurePosixPath


def audio_format(data: bytes, filename: str = "") -> str:
    if not data:
        raise ValueError("Cannot transcribe empty audio.")
    if data.startswith(b"OggS"):
        return "ogg"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 0xE0 == 0xE0):
        return "aac" if data[1] & 0xF6 == 0xF0 else "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if data.startswith(b"FORM") and data[8:12] in (b"AIFF", b"AIFC"):
        return "aiff"
    extension = PurePosixPath(filename or "").suffix.lower().lstrip(".")
    extension = {"opus": "ogg", "oga": "ogg", "mp4": "m4a", "aif": "aiff"}.get(extension, extension)
    if extension in {"ogg", "wav", "mp3", "flac", "m4a", "aac", "webm", "aiff"}:
        return extension
    raise ValueError("Unsupported audio container; send OGG, WAV, MP3, FLAC, M4A, AAC, WebM or AIFF.")


def parse_transcription(response: str, structured: bool) -> str:
    if structured:
        try:
            parsed = json.loads(response)
            if isinstance(parsed, dict) and isinstance(parsed.get("transcription"), str):
                return parsed["transcription"]
        except (TypeError, ValueError):
            pass
    return response
