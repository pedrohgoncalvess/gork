from external.waha.base import chat_id, request
from external.waha.identifiers import message_payload, sent_response
from external.waha.presence import calculate_typing_delay_ms, send_presence


def is_instant_command_message(message: str) -> bool:
    return bool(message and (
        message.strip().startswith(("!help", "!model", "!status", "!usage", "!resume"))
        or any(signature in message for signature in (
            "🤖 *COMANDOS DO GORK*", "🤖 *MODELOS EM USO*",
            "🤖 Robo do mito está pronto", "O robo do mito não está pronto",
            "📊 *SEU CONSUMO DE TOKENS*", "📊 *RELATÓRIO DE CONSUMO DE TOKENS*",
        ))
    ))


async def send_message(contact_id: str, message: str, message_id: str = None,
                       is_first: bool = True, simulate_typing: bool = True,
                       mentioned: list[str] | None = None):
    if simulate_typing and not is_instant_command_message(message):
        await send_presence(contact_id, "composing", calculate_typing_delay_ms(message))
    payload = await message_payload(contact_id, message_id if is_first else None)
    payload["text"] = message
    if mentioned:
        payload["mentions"] = list(dict.fromkeys(chat_id(value) for value in mentioned))
    response = await request("POST", "/api/sendText", payload=payload)
    return await sent_response(response, contact_id)
