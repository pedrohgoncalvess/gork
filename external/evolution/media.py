import base64

import httpx

from external.evolution.base import evolution_instance_name, evolution_api_key, evolution_api


async def download_media(message_id: str, convert_to_mp4: bool = False) -> tuple[bytes, str]:
    media_url = f"{evolution_api}/chat/getBase64FromMediaMessage/{evolution_instance_name}"

    payload = {
        "message": {
            "key": {
                "id" :message_id,
            }
        },
        "convertToMp4": convert_to_mp4
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


async def send_media(contact_id: str, file_path: str):
    media_url = f"{evolution_api}/message/sendMedia/{evolution_instance_name}"
    with open(file_path, "rb") as f:
        file_data = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "number": contact_id,
        "media": file_data,
        "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", # TODO: add a map with file extension -> mimetype
        "fileName":file_path.split("/")[-1],
        "mediatype": "document"
    }

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(media_url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()