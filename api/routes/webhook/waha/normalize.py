"""Convert WAHA/GOWS events to the message contract consumed by Gork's handlers."""
from copy import deepcopy
from datetime import datetime, timezone
import re

from external.waha.identifiers import stanza_id


def legacy_jid(value: str | None) -> str:
    return (value or "").replace("@c.us", "@s.whatsapp.net")


def unwrap_message(message: dict) -> dict:
    while isinstance(message, dict):
        wrapped = next((message[key].get("message") for key in (
            "ephemeralMessage", "viewOnceMessage", "viewOnceMessageV2",
            "viewOnceMessageV2Extension", "documentWithCaptionMessage",
        ) if isinstance(message.get(key), dict) and message[key].get("message")), None)
        if wrapped is None:
            return message
        message = wrapped
    return {}


def native_message(payload: dict) -> dict:
    raw = payload.get("_data") or {}
    # replyTo._data may be the protobuf message itself, without a GOWS envelope.
    native = raw.get("Message") or raw.get("RawMessage")
    if not native and any(key == "conversation" or key.endswith("Message") for key in raw):
        native = raw
    return unwrap_message(deepcopy(native or {}))


def remote_address(payload: dict) -> str:
    identifier = payload.get("id") or ""
    embedded = identifier.split("_", 2)
    embedded = embedded[1] if len(embedded) == 3 else ""
    from_me = payload.get("fromMe", identifier.startswith("true_"))
    candidates = [payload.get("chatId"), embedded if embedded.endswith("@g.us") else None,
                  payload.get("from") if str(payload.get("from", "")).endswith("@g.us") else None,
                  payload.get("to") if from_me else payload.get("from"), embedded]
    return next((value for value in candidates if isinstance(value, str) and value), "")


def normalize_webhook(body: dict) -> dict | None:
    if body.get("event") not in ("message.any", "message"):
        return None
    payload = body.get("payload") or {}
    remote = remote_address(payload)
    if not re.fullmatch(r"\d+(?:-\d+)?@(?:c\.us|s\.whatsapp\.net|lid|g\.us)", remote):
        return None
    identifier = payload.get("id")
    if not identifier:
        raise ValueError("WAHA message is missing its ID")
    info = (payload.get("_data") or {}).get("Info") or {}
    from_me = payload.get("fromMe", identifier.startswith("true_"))
    message = native_message(payload)
    media = payload.get("media") or {}
    mime = media.get("mimetype", "").lower()
    message_type = next((kind + "Message" for kind in (
        "sticker", "image", "video", "audio", "document"
    ) if kind + "Message" in message), None)
    if not message_type and payload.get("hasMedia"):
        kind = ("sticker" if mime.startswith("image/webp") else
                next((kind for kind in ("image", "audio", "video") if mime.startswith(kind + "/")), "document"))
        message_type = kind + "Message"
        message[message_type] = {"mimetype": mime}
    message_type = message_type or ("extendedTextMessage" if "extendedTextMessage" in message else "conversation")
    context = deepcopy(next((value["contextInfo"] for value in message.values()
                            if isinstance(value, dict) and isinstance(value.get("contextInfo"), dict)), {}))
    if context.get("stanzaID"):
        context["stanzaId"] = context.pop("stanzaID")
    reply = payload.get("replyTo") or {}
    quote_id = context.get("stanzaId") or reply.get("id")
    if quote_id:
        context["stanzaId"] = stanza_id(quote_id)
        quoted = unwrap_message(context.get("quotedMessage") or native_message(reply))
        if not quoted and reply.get("media"):
            mime_type = reply["media"].get("mimetype", "")
            quote_kind = ("sticker" if mime_type.startswith("image/webp") else
                          next((kind for kind in ("image", "audio", "video") if mime_type.startswith(kind + "/")), "document"))
            quoted = {quote_kind + "Message": {"caption": reply.get("body", "")}}
        if not quoted and reply.get("body"):
            quoted = {"conversation": reply["body"]}
        context["quotedMessage"] = quoted
    mentions = context.get("mentionedJID") or context.get("mentionedJid") or payload.get("mentionedIds") or payload.get("mentions") or []
    context["mentionedJid"] = [legacy_jid(value) for value in mentions if isinstance(value, str)]
    # Text is also supplied at top level for existing command and caption parsing.
    message["conversation"] = (payload.get("body") or message.get("conversation")
                               or message.get("extendedTextMessage", {}).get("text")
                               or message.get(message_type, {}).get("caption") or "")
    sender = payload.get("participant") or info.get("Sender") or payload.get("from") or ""
    sender_alt = info.get("SenderAlt") or payload.get("participantAlt") or ""
    remote_alt = info.get("ChatAlt") or payload.get("fromAlt") or ""
    # For DMs GOWS SenderAlt carries the hidden/phone alias, just like groups.
    if not remote.endswith("@g.us") and not from_me:
        remote_alt = remote_alt or sender_alt
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, (float, int)):
        raise ValueError("WAHA message is missing its timestamp")
    return {
        "event": "send.message" if from_me else "messages.upsert",
        "instance": body.get("session"),
        "date_time": datetime.now(timezone.utc).isoformat(),
        "data": {
            "key": {"id": stanza_id(identifier), "fromMe": from_me,
                    "remoteJid": legacy_jid(remote), "remoteJidAlt": legacy_jid(remote_alt),
                    "participant": legacy_jid(sender), "participantAlt": legacy_jid(sender_alt)},
            "pushName": payload.get("pushName") or info.get("PushName") or sender.split("@")[0],
            "messageTimestamp": timestamp, "messageType": message_type,
            "message": message, "contextInfo": context,
        },
    }
