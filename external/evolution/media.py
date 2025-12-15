import httpx

from external.evolution.base import evolution_instance_name, evolution_api_key, evolution_api


async def download_media(message_id: str) -> tuple[bytes, str]:
    media_url = f"{evolution_api}/chat/getBase64FromMediaMessage/{evolution_instance_name}"

    payload = {
        "message": {
            "key": {
                "id" :message_id,
            }
        },
        "convertToMp4": False
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(media_url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()

        result = response.json()

        if 'base64' in result:
            return result["base64"], result["fileName"]