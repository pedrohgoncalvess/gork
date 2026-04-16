from typing import Optional

from external.evolution import send_message, send_audio
from api.routes.webhook.evolution.functions import generic_conversation
from database.models.base import User
from tts import text_to_speech

async def handle_generic_conversation(
        remote_id: str,
        message_id: str,
        user: User,
        treated_text: str,
        context: dict[str, str],
        group_id: Optional[int] = None,
        audio: bool = False
):
    is_group = True if group_id else False
    response_message = await generic_conversation(group_id, user.name, treated_text, user.id, context, is_group)

    if audio:
        audio_base64 = await text_to_speech(
            response_message.get("text"),
            language=response_message.get("language")
        )
        await send_audio(remote_id, audio_base64, message_id)
        return
    else:
        response_text = f"{response_message.get('text')}"
        await send_message(remote_id, response_text, message_id)
        return
