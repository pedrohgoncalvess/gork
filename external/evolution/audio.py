import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name


async def send_audio(contact_id: str, audio_base64: str, message_id: str):
    url = f"{evolution_api}/message/sendWhatsAppAudio/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "audio": audio_base64,
        "quoted": {
            "key": {"id": message_id},
        }
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=60)
        return response.json()
