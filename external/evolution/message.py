import httpx

from external.evolution.base import evolution_api, evolution_api_key, evolution_instance_name
from external.evolution.presence import calculate_typing_delay_ms, send_presence


def is_instant_command_message(message: str) -> bool:
    if not message:
        return False
    msg_clean = message.strip()
    if msg_clean.startswith(("!help", "!model", "!status", "!consumption", "!resume")):
        return True
    instant_signatures = (
        "🤖 *COMANDOS DO GORK*",
        "🤖 *MODELOS EM USO*",
        "🤖 Robo do mito está pronto",
        "O robo do mito não está pronto",
        "📊 *SEU CONSUMO DE TOKENS*",
        "📊 *RELATÓRIO DE CONSUMO DE TOKENS*",
    )
    return any(sig in msg_clean for sig in instant_signatures)


async def send_message(
    contact_id: str,
    message: str,
    message_id: str = None,
    is_first: bool = True,
    simulate_typing: bool = True,
):
    headers = {
        "Content-Type": "application/json",
        "apikey": evolution_api_key
    }

    url_message = f"{evolution_api}/message/sendText/{evolution_instance_name}"

    if simulate_typing and not is_instant_command_message(message):
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
