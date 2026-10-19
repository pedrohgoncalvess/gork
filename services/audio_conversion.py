import asyncio
import subprocess


async def audio_to_wav(audio_bytes: bytes) -> bytes:
    """Normalize incoming voice notes using the existing FFmpeg runtime."""
    if not audio_bytes:
        raise ValueError("Cannot convert empty audio.")
    # A worker thread also works with Windows selector event loops, whose
    # asyncio subprocess transport is unavailable. Never block API workers.
    result = await asyncio.to_thread(
        subprocess.run,
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
         "-f", "wav", "pipe:1"],
        input=audio_bytes, capture_output=True, timeout=60,
    )
    output, error = result.stdout, result.stderr
    if result.returncode != 0 or not output.startswith(b"RIFF") or output[8:12] != b"WAVE":
        raise RuntimeError(f"FFmpeg could not decode audio: {error.decode(errors='replace')[:500]}")
    return output
