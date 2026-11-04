import json
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text
import httpx

from api.routes.webhook.waha.processors import (
    process_group_message,
    process_private_message,
    process_sent_message,
)
from database import PgConnection
from external.waha import send_message
from external.waha.base import request, segment, waha_session
from external.waha.identifiers import get_reference, save_reference
from external.waha.base import chat_id
from api.routes.webhook.waha.normalize import normalize_webhook, remote_address
from services.conversation_lock import serialize_direct_message
from services.setup import settings, map_principal
from services.ban_cache import decision as cached_ban_decision


async def moderate_group_message(body: dict) -> bool:
    data = body["data"]
    remote = data["key"]["remoteJid"]
    if data["key"].get("fromMe") or not remote.endswith("@g.us"):
        return False
    from services.group_ban import enforce_ban
    cached = await cached_ban_decision(data, remote)
    if cached is False:
        return False
    if cached is True:
        return await enforce_ban(data, remote, known_active=True)
    if (await settings())["test_mode"]:
        return False
    return await enforce_ban(data, remote)


async def persist_ban_deletion(body: dict, normalized: dict):
    payload = body['payload']
    data = normalized['data']
    key = data['key']
    # The DELETE has completed. Retain the received content/metadata, not media downloads.
    async with PgConnection() as db:
        await db.execute(text('''INSERT INTO manager.group_ban_deletion
            (session, chat_id, provider_id, message_id, sender_id, payload)
            VALUES (:session, :chat, :provider, :message, :sender, CAST(:payload AS jsonb))
            ON CONFLICT (session, chat_id, provider_id) DO NOTHING'''),
            {'session': waha_session, 'chat': key['remoteJid'], 'provider': payload['id'],
             'message': key['id'], 'sender': key['participant'], 'payload': json.dumps(payload)})
        await db.commit()
    await save_reference(payload, key['remoteJid'])


async def process_waha_webhook(body: dict, scheduler: AsyncIOScheduler):
    if body.get("event") in ("poll.vote", "poll.vote.failed"):
        from services.group_ban import record_vote, record_failed_vote
        if not (await settings())["test_mode"]:
            if body["event"] == "poll.vote":
                await record_vote(body)
            else:
                await record_failed_vote(body)
        return
    normalized = normalize_webhook(body)
    if normalized is None:
        return
    payload = body["payload"]
    remote = remote_address(payload)
    key = normalized["data"]["key"]
    key["providerId"] = payload["id"]
    # Delete before identity lookups, reference writes, media downloads or agents.
    if await moderate_group_message(normalized):
        await persist_ban_deletion(body, normalized)
        return
    if body.get("me", {}).get("id"):
        await map_principal(body["me"])
    # Resolve missing phone/LID aliases before matching existing users and whitelist.
    if not key["fromMe"]:
        is_group = remote.endswith("@g.us")
        original = key["participant"] if is_group else key["remoteJid"]
        alternate_key = "participantAlt" if is_group else "remoteJidAlt"
        if original.endswith("@lid") and not key.get(alternate_key):
            try:
                result = await request("GET", f"/api/{segment(waha_session)}/lids/{segment(original)}")
                key[alternate_key] = (result.get("pn") or "").replace("@c.us", "@s.whatsapp.net")
            except httpx.HTTPStatusError as error:
                if error.response.status_code != 404:
                    raise
    await save_reference(payload, remote)
    reply = payload.get("replyTo") or {}
    if reply.get("id"):
        # Keep a complete reference captured from its original message event.
        if not await get_reference(reply["id"]):
            await save_reference(reply, remote)
    else:
        context = normalized["data"]["contextInfo"]
        quote_id = context.get("stanzaId")
        if quote_id and not await get_reference(quote_id):
            participant = context.get("participant") or reply.get("participant") or ""
            me = body.get("me") or {}
            own_ids = [me.get("id"), me.get("lid")]
            from_me = any(value and chat_id(value) == chat_id(participant)
                          for value in own_ids if participant)
            await save_reference({"id": f"{str(from_me).lower()}_{chat_id(remote)}_{quote_id}",
                                  "media": reply.get("media")}, remote)
    await process_webhook(normalized, scheduler)

async def process_webhook(body: dict, scheduler: AsyncIOScheduler):
    async with PgConnection() as db:
        event_type = body.get("event")
        event_data = body.get("data")

        valid_events = ["messages.upsert", "send.message"]
        if event_type not in valid_events:
            return

        remote_id = event_data.get("key", {}).get("remoteJid", "")
        alt_id = event_data.get("key", {}).get("remoteJidAlt", "")

        is_private = not remote_id.endswith("@g.us")
        phone_number = next((value.removesuffix("@s.whatsapp.net")
                             for value in (remote_id, alt_id)
                             if value.endswith("@s.whatsapp.net")), None)
        if is_private:
            identity = next((value for value in (remote_id, alt_id) if value.endswith("@lid")), remote_id)
            remote_id = identity.split("@")[0]
        else:
            remote_id = remote_id.removesuffix("@g.us")

        config = await settings(db)
        if config["test_mode"]:
            # Ignore other chats silently; groups must never bypass test isolation.
            if not is_private or phone_number != config["test_number"]:
                return

        if event_type == "send.message":
            await process_sent_message(body, remote_id, db, not is_private)
            return

        if not is_private:
            await process_group_message(
                body, f"{remote_id}@g.us", db, scheduler
            )
        elif is_private:
            async with serialize_direct_message(phone_number or remote_id):
                await process_private_message(
                    body, event_data, remote_id, phone_number, db, scheduler
                )
