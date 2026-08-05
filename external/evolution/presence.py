import base64
import io
import wave

import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name
from log import logger

MIN_TYPING_DELAY_MS = 800
MAX_TYPING_DELAY_MS = 12000
BASE_TYPING_DELAY_MS = 500
MS_PER_CHARACTER = 65
MS_PER_LINE_BREAK = 250

MIN_AUDIO_DELAY_MS = 1000
MAX_AUDIO_DELAY_MS = 30000


def calculate_typing_delay_ms(message: str) -> int:
    if not message:
        return MIN_TYPING_DELAY_MS

    visible_chars = len(message.strip())
    line_breaks = message.count("\n")
    delay = (
        BASE_TYPING_DELAY_MS
        + visible_chars * MS_PER_CHARACTER
        + line_breaks * MS_PER_LINE_BREAK
    )

    return max(MIN_TYPING_DELAY_MS, min(delay, MAX_TYPING_DELAY_MS))


def calculate_audio_delay_ms(audio_input: str | bytes) -> int:
    if not audio_input:
        return MIN_AUDIO_DELAY_MS

    if isinstance(audio_input, str):
        try:
            clean_b64 = audio_input.split(",", 1)[1] if "," in audio_input else audio_input
            raw_bytes = base64.b64decode(clean_b64)
        except Exception:
            return MIN_AUDIO_DELAY_MS
    else:
        raw_bytes = audio_input

    if not raw_bytes:
        return MIN_AUDIO_DELAY_MS

    # Try parsing WAV header first (common for Piper TTS)
    if raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:16]:
        try:
            with wave.open(io.BytesIO(raw_bytes), "rb") as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                if rate > 0:
                    duration_ms = int((frames / float(rate)) * 1000)
                    return max(MIN_AUDIO_DELAY_MS, min(duration_ms, MAX_AUDIO_DELAY_MS))
        except Exception:
            pass

    # Fallback for compressed audio formats (OGG Opus, MP3, M4A)
    # Average Opus / WhatsApp voice note bitrate is ~32kbps = 4000 bytes/sec
    if raw_bytes.startswith(b"RIFF"):
        bytes_per_sec = 44100.0
    else:
        bytes_per_sec = 4000.0

    estimated_ms = int((len(raw_bytes) / bytes_per_sec) * 1000)
    return max(MIN_AUDIO_DELAY_MS, min(estimated_ms, MAX_AUDIO_DELAY_MS))


async def send_presence(
    contact_id: str,
    presence: str = "composing",
    delay_ms: int = 1000,
) -> None:
    """
    Centralized function to send WhatsApp presence status via Evolution API.
    presence: "composing" (typing text) or "recording" (recording audio).
    """
    url_send_presence = f"{evolution_api}/chat/sendPresence/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "delay": delay_ms,
        "presence": presence,
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key,
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url_send_presence, json=payload, headers=headers, timeout=60
            )
            response.raise_for_status()
        except Exception as e:
            await logger.error(
                "EvolutionPresence",
                f"Erro ao enviar presença ({presence}) para {contact_id}",
                str(e),
            )
