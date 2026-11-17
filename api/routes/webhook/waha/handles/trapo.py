"""
Handler for the !trapo command.

Renders a football "trapo" (two-band banner in a team's colors) through the
trapo generator API. The phrase comes from the message itself or, when the
message only has the command, from the quoted message.

    !trapo eh os guri da catequese :time=gremio
    !trapo vendi o carro | pra pagar o sócio torcedor :inter
"""

from __future__ import annotations

import base64

from api.routes.webhook.waha.handles.core import clean_text
from external.trapo import TrapoError, generate_trapo
from external.waha import send_image, send_message
from log import logger


async def handle_trapo_command(
    remote_id: str,
    message_id: str,
    conversation: str,
    db_message,
    db,
) -> None:
    from database.operations.content import MessageRepository

    quoted_phrase = None
    if not clean_text(conversation) and db_message.quoted_message_id:
        quoted = await MessageRepository(db).find_by_id(db_message.quoted_message_id)
        if quoted and quoted.content:
            quoted_phrase = quoted.content.strip()

    try:
        image = await generate_trapo(conversation, quoted_phrase)
    except TrapoError as exc:
        await send_message(remote_id, f"🏳️ {exc}", message_id)
        return
    except Exception as exc:
        await logger.error("TrapoHandle", "RequestError", str(exc))
        await send_message(remote_id, "⚠️ Não consegui gerar o trapo. Tenta de novo!", message_id)
        return

    await send_image(
        remote_id,
        base64.b64encode(image).decode(),
        filename="trapo.png",
        mimetype="image/png",
    )
