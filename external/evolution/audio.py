import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name
from external.evolution.presence import calculate_audio_delay_ms, send_presence


async def send_audio(contact_id: str, audio_base64: str, message_id: str | None = None):
    url = f"{evolution_api}/message/sendWhatsAppAudio/{evolution_instance_name}"

    delay = calculate_audio_delay_ms(audio_base64)
    await send_presence(contact_id, presence="recording", delay_ms=delay)

    payload = {
        "number": contact_id,
        "audio": audio_base64,
    }

    if message_id:
        payload["quoted"] = {
            "key": {"id": message_id},
        }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=60)
        return response.json()
