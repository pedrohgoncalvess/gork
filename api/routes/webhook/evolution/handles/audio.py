from typing import Optional

from api.routes.webhook.evolution.functions import transcribe_audio
from external.evolution import send_message


async def handle_transcribe_command(
        remote_id: str,
        message_id: str,
        body: dict,
        user_id: int,
        group_id: Optional[int] = None
):
    transcribed_audio = await transcribe_audio(body, user_id, group_id)
    transcribed_audio = f"_{transcribed_audio.strip()}_"
    await send_message(remote_id, transcribed_audio, message_id)
