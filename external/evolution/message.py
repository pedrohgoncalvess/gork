import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name


async def send_message(contact_id: str, message: str, message_id: str = None):
    url = f"{evolution_api}/message/sendText/{evolution_instance_name}"

    payload = {
        "number": contact_id,
        "text": message,
    }

    if message_id:
        payload.update({"quoted": {"key": {"id": message_id}}})

    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=60)
        return response.json()
