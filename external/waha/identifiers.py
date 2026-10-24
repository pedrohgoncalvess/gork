"""Keep historical stanza IDs while retaining WAHA's complete message references."""
import json
import re

from security.sql import typed_text
from security.types import EncryptedText, EncryptedJSON

from database import PgConnection
from external.waha.base import chat_id, waha_session


def text(sql):
    binds = {'provider_id': EncryptedText('reference.provider_id'),
             'chat_id': EncryptedText('identity', True), 'media': EncryptedJSON('reference.media')}
    columns = {'provider_id': EncryptedText('reference.provider_id'),
               'chat_id': EncryptedText('identity', True), 'media': EncryptedJSON('reference.media'),
               'phone_number': EncryptedText('identity', True)}
    return typed_text(sql, binds=binds,
                      columns=columns if sql.lstrip().upper().startswith('SELECT') else None)


def stanza_id(value: str) -> str:
    value = re.sub(r"^(?:true|false)_[^_]+_", "", value)
    return re.sub(r"_[^_]+@(?:c\.us|s\.whatsapp\.net|lid|g\.us)$", "", value)


async def save_reference(payload: dict, destination: str) -> None:
    identifier = payload.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("WAHA message response has no ID")
    if not re.match(r"^(true|false)_", identifier):
        # Some replyTo records only expose the native stanza ID.
        identifier = await reply_id(identifier, destination)
    async with PgConnection() as db:
        await db.execute(text("""
            INSERT INTO content.waha_message_reference
                (session, message_id, provider_id, chat_id, media)
            VALUES (:session, :message_id, :provider_id, :chat_id, CAST(:media AS jsonb))
            ON CONFLICT (session, message_id) DO UPDATE SET
                provider_id = EXCLUDED.provider_id, chat_id = EXCLUDED.chat_id,
                media = COALESCE(EXCLUDED.media, waha_message_reference.media)
        """), {
            "session": waha_session, "message_id": stanza_id(identifier),
            "provider_id": identifier, "chat_id": chat_id(destination),
            "media": payload.get("media") or None,
        })
        await db.commit()


async def get_reference(message_id: str) -> dict | None:
    async with PgConnection() as db:
        result = await db.execute(text("""
            SELECT provider_id, chat_id, media FROM content.waha_message_reference
            WHERE session = :session AND message_id = :message_id
        """), {"session": waha_session, "message_id": stanza_id(message_id)})
        row = result.mappings().first()
        return dict(row) if row else None


async def reply_id(message_id: str, destination: str) -> str:
    if re.match(r"^(true|false)_", message_id):
        return message_id
    reference = await get_reference(message_id)
    if reference:
        return reference["provider_id"]
    # Historical messages have no WAHA reference; recover their direction.
    from utils import get_instance_number
    async with PgConnection() as db:
        result = await db.execute(text("""
            SELECT u.phone_number FROM content.message m
            JOIN base."user" u ON u.id = m.user_id WHERE m.message_id = :id
        """), {"id": message_id})
        sender = result.scalar_one_or_none()
    from_me = bool(sender and sender == (await get_instance_number()))
    return f"{str(from_me).lower()}_{chat_id(destination)}_{message_id}"


async def message_payload(destination: str, quoted: str | None = None) -> dict:
    payload = {"session": waha_session, "chatId": chat_id(destination)}
    if quoted:
        payload["reply_to"] = await reply_id(quoted, destination)
    return payload


async def sent_response(response: dict, destination: str) -> dict:
    await save_reference(response, destination)
    return {
        **response, "key": {"id": stanza_id(response["id"])},
        "messageTimestamp": response.get("timestamp"),
    }
