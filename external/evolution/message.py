import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name


MIN_TYPING_DELAY_MS = 800
MAX_TYPING_DELAY_MS = 12000
BASE_TYPING_DELAY_MS = 500
MS_PER_CHARACTER = 65
MS_PER_LINE_BREAK = 250


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


async def send_message(contact_id: str, message: str, message_id: str = None, is_first: bool = True):
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    url_message = f"{evolution_api}/message/sendText/{evolution_instance_name}"
    url_send_presence = f"{evolution_api}/message/sendPresence/{evolution_instance_name}"

    delay = calculate_typing_delay_ms(message)

    payload_send_presence = {
        "number": contact_id,
        "delay": delay,
        "presence": "composing"
    }

    async with httpx.AsyncClient() as client:
        _ = await client.post(url_send_presence, json=payload_send_presence, headers=headers, timeout=60)

    payload = {
        "number": contact_id,
        "text": message,
    }

    if message_id and is_first:
        payload.update({"quoted": {"key": {"id": message_id}}})

    async with httpx.AsyncClient() as client:
        response = await client.post(url_message, json=payload, headers=headers, timeout=60)
        return response.json()
