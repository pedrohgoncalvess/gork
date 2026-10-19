from external.waha.media import send_file
from external.waha.presence import calculate_audio_delay_ms, send_presence


async def send_audio(contact_id: str, audio_base64: str, message_id: str | None = None):
    await send_presence(contact_id, "recording", calculate_audio_delay_ms(audio_base64))
    # TTS returns WAV. WAHA/FFmpeg converts it to an OGG Opus voice note.
    return await send_file(contact_id, "/api/sendVoice", audio_base64,
                           "gork.wav", "audio/wav", message_id, convert=True)
