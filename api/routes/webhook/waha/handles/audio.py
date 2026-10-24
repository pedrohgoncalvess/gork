from typing import Optional

from agents.transcriber.agent import transcribe_audio
from external.waha import send_message


async def handle_transcribe_command(
    remote_id: str, message_id: str, body: dict,
    user_id: int, group_id: Optional[int] = None,
):
    transcription = await transcribe_audio(body, user_id, group_id, command=True)
    await send_message(remote_id, f"_{transcription.strip()}_", message_id)
