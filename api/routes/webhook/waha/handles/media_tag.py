from external.waha import send_message
from services.media_tags import mark_media


async def handle_tag_command(remote_id, db_message, context):
    context = context or {}
    source_id = context.get("audio_message") or context.get("audio_quote")
    if not source_id:
        await send_message(remote_id, "Responda a um áudio com !tag para marcá-lo.", db_message.message_id)
        return
    await mark_media(db_message.user_id, "audio", source_id, db_message.message_id, db_message.created_at)
    await send_message(remote_id, "Áudio marcado.", db_message.message_id)
