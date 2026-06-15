"""
High-level handler for the !philo command.

Called from the processor when a message starts with !philo.
Accepts an optional :quote=<philosopher_name> parameter.

If the message quotes another message, the quoted text is used as the
displayed phrase; otherwise, the remaining text in the current message
is used.
"""

from __future__ import annotations

from typing import Optional

from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.philo import build_philo_image
from external.evolution import send_image, send_message
from log import logger


async def handle_philo_command(
    remote_id: str,
    message_id: str,
    conversation: str,
    db_message,
    db,
    params: dict,
) -> None:
    """
    Build a philosopher image and send it.

    Parameters
    ----------
    remote_id       : WhatsApp JID to send the result to.
    message_id      : ID of the triggering message (used for quoting).
    conversation    : Full raw message content.
    db_message      : ORM Message object.
    db              : Async DB session.
    params          : Parsed parameters dict (from services.parse_params).
    """
    from database.operations.content import MessageRepository

    philosopher_key: Optional[str] = params.get("quote")

    # --- Resolve the quote text ---
    quote_text: Optional[str] = None

    # 1. If the message is quoting another message, use that content
    if db_message.quoted_message_id:
        message_repo = MessageRepository(db)
        quoted = await message_repo.find_by_id(db_message.quoted_message_id)
        if quoted and quoted.content:
            quote_text = quoted.content.strip()

    # 2. Fall back to text in the current message (excluding command/params)
    if not quote_text:
        cleaned = clean_text(conversation)
        if cleaned:
            quote_text = cleaned

    if not quote_text:
        await send_message(
            remote_id,
            "📜 Para usar o *!philo*, cite uma mensagem ou escreva um texto após o comando.\n"
            "Exemplo: _!philo :quote=socrates Eu gosto de pudim_",
            message_id,
        )
        return

    try:
        img_b64, philo = build_philo_image(quote_text, philosopher_key)
    except Exception as exc:
        await logger.error("PhiloHandle", "BuildError", str(exc))
        await send_message(
            remote_id,
            "⚠️ Não consegui gerar a imagem filosófica. Tenta de novo!",
            message_id,
        )
        return

    await send_image(remote_id, img_b64)
