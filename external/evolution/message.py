import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name
from external.evolution.presence import calculate_typing_delay_ms, send_presence


async def send_message(contact_id: str, message: str, message_id: str = None, is_first: bool = True):
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    url_message = f"{evolution_api}/message/sendText/{evolution_instance_name}"

    delay = calculate_typing_delay_ms(message)
    await send_presence(contact_id, presence="composing", delay_ms=delay)

    payload = {
        "number": contact_id,
        "text": message,
    }

    if message_id and is_first:
        payload.update({"quoted": {"key": {"id": message_id}}})

    async with httpx.AsyncClient() as client:
        response = await client.post(url_message, json=payload, headers=headers, timeout=60)
        return response.json()
