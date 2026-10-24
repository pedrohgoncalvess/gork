"""Import WAHA contacts/history without dispatching commands or sending messages."""
import asyncio
import calendar
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import HTTPException
from security.sql import typed_text
from security.types import EncryptedText
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from api.admin.connection import provider_errors
from api.routes.webhook.waha.normalize import normalize_webhook, remote_address
from database import PgConnection
from database.models.content import Message
from database.operations.base import GroupRepository, UserRepository
from external.waha.base import request, segment, waha_session
from external.waha.identifiers import save_reference
from external.waha.group import get_group_info
from services.setup import address_part, discover_principal


def text(sql):
    return typed_text(sql, binds={'error': EncryptedText('sync.error')},
                      columns={'error': EncryptedText('sync.error')} if sql.lstrip().upper().startswith('SELECT') or 'RETURNING *' in sql else None)


tasks = set()
PAGE_SIZE = 100


def time_window(data, now=None):
    now = now or datetime.now(timezone.utc)
    if data.period == "custom":
        return data.start, data.end
    if data.period == "all":
        return None, now
    days = {"3d": 3, "5d": 5, "1w": 7, "2w": 14}
    if data.period in days:
        return now - timedelta(days=days[data.period]), now
    months = 1 if data.period == "1m" else 3
    year, month = divmod(now.year * 12 + now.month - 1 - months, 12)
    month += 1
    return now.replace(year=year, month=month, day=min(now.day, calendar.monthrange(year, month)[1])), now


async def latest():
    async with PgConnection() as db:
        await expire_jobs(db)
        row = (await db.execute(text("SELECT * FROM base.sync_job ORDER BY started_at DESC LIMIT 1"))).mappings().first()
        return dict(row) if row else None


async def expire_jobs(db):
    await db.execute(text("""UPDATE base.sync_job SET status='failed',
        error=:error, updated_at=now()
        WHERE status='running' AND updated_at < now() - interval '5 minutes'"""), {'error': 'Sincronização interrompida. Inicie novamente para continuar sem duplicar mensagens.'})
    await db.commit()


async def start(data):
    async with provider_errors():
        principal = await discover_principal()
    if not principal:
        raise HTTPException(409, "Conecte o WhatsApp antes de sincronizar.")
    async with PgConnection() as db:
        await expire_jobs(db)
        try:
            row = (await db.execute(text("INSERT INTO base.sync_job (phase) VALUES (:phase) RETURNING *"),
                                    {"phase": "contacts" if data.contacts else "history"})).mappings().one()
            job = dict(row)
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Já existe uma sincronização em andamento.") from None
    task = asyncio.create_task(run(job["id"], data, principal), name=f"sync:{job['id']}")
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return job


async def progress(job_id, counts, status="running", error=None, phase=None):
    async with PgConnection() as db:
        result = await db.execute(text("""UPDATE base.sync_job SET contacts=:contacts, messages=:messages,
            skipped=:skipped, status=:status, error=:error, phase=COALESCE(:phase,phase), updated_at=now()
            WHERE id=:id AND status='running' RETURNING id"""),
            dict(counts, id=job_id, status=status, error=error, phase=phase))
        alive = result.scalar_one_or_none() is not None
        await db.commit()
        if not alive:
            raise RuntimeError("Sync job no longer active")


async def pages(path, params, *, stop_on_short_page=False):
    offset = 0
    previous = None
    while True:
        # Contacts use one look-ahead record to detect the end even when their
        # total is an exact multiple of PAGE_SIZE, without an out-of-range call.
        limit = PAGE_SIZE + 1 if stop_on_short_page else PAGE_SIZE
        batch = await request("GET", path, params={**params, "limit": limit, "offset": offset})
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected WAHA response")
        if not batch:
            return
        signature = tuple(str(entry.get("id")) for entry in batch)
        if signature == previous:
            raise RuntimeError("WAHA pagination did not advance")
        previous = signature
        yield batch[:PAGE_SIZE] if stop_on_short_page else batch
        # GOWS contacts return HTTP 500 for offsets beyond the final page.
        if stop_on_short_page and len(batch) <= PAGE_SIZE:
            return
        # WAHA may return fewer than limit even when further pages exist.
        offset += PAGE_SIZE


async def contact_user(db, identifier, name=None, phone=None):
    number = address_part(identifier, ("@c.us", "@s.whatsapp.net")) or phone
    lid = address_part(identifier, ("@lid",))
    if lid and not number:
        try:
            alias = await request("GET", f"/api/{segment(waha_session)}/lids/{segment(identifier)}")
            number = address_part(alias.get("pn"), ("@c.us", "@s.whatsapp.net"))
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
    elif number and not lid:
        try:
            alias = await request("GET", f"/api/{segment(waha_session)}/lids/pn/{segment(number + '@c.us')}")
            lid = address_part(alias.get("lid"), ("@lid",))
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
    if not lid and not number:
        return None
    return await UserRepository(db).find_or_create(lid=lid or number, phone_number=number, name=name)


async def import_message(payload, principal):
    normalized = normalize_webhook({"event": "message.any", "session": waha_session, "payload": payload})
    if not normalized:
        return False
    data = normalized["data"]
    key = data["key"]
    remote = remote_address(payload)
    async with PgConnection() as db:
        group_id = None
        chat_user_id = None
        if remote.endswith("@g.us"):
            groups = GroupRepository(db)
            group = await groups.find_or_create(group_jid=remote.removesuffix("@g.us"))
            if not group.name:
                try:
                    info = await get_group_info(remote)
                except httpx.HTTPStatusError as error:
                    # Historical groups may no longer be accessible to this account.
                    if error.response.status_code != 404:
                        raise
                else:
                    group = await groups.find_or_create(group_jid=remote.removesuffix("@g.us"),
                        name=info["subject"], description=info.get("desc"))
            group_id = group.id
        else:
            alias = address_part(key.get("remoteJidAlt"), ("@s.whatsapp.net",))
            contact = await contact_user(db, remote, name=None if key["fromMe"] else data["pushName"], phone=alias)
            if not contact:
                return False
            chat_user_id = contact.id
        if key["fromMe"]:
            user_id = principal["user_id"]
        elif group_id:
            alias = address_part(key.get("participantAlt"), ("@s.whatsapp.net",))
            sender = await contact_user(db, key["participant"], data["pushName"], alias)
            if not sender:
                return False
            user_id = sender.id
        else:
            user_id = chat_user_id
        # ON CONFLICT keeps live-message media, favourites, and existing content intact.
        stmt = insert(Message).values(message_id=key["id"], user_id=user_id,
            chat_user_id=chat_user_id, group_id=group_id, content=data["message"]["conversation"] or None,
            created_at=datetime.fromtimestamp(data["messageTimestamp"], timezone.utc).replace(tzinfo=None))
        result = await db.execute(stmt.on_conflict_do_nothing(index_elements=["message_id"]).returning(Message.id))
        inserted = result.scalar_one_or_none() is not None
        await db.commit()
    await save_reference(payload, remote)
    return inserted


async def run(job_id, data, principal):
    counts = {"contacts": 0, "messages": 0, "skipped": 0}
    phase = "contacts" if data.contacts else "history"
    since, until = time_window(data)
    try:
        if data.contacts:
            async for batch in pages("/api/contacts/all", {"session": waha_session, "sortBy": "id", "sortOrder": "asc"}, stop_on_short_page=True):
                for entry in batch:
                    async with PgConnection() as db:
                        user = await contact_user(db, entry.get("id"), entry.get("name") or entry.get("pushname") or entry.get("pushName"))
                    counts["contacts" if user else "skipped"] += 1
                    await progress(job_id, counts)
        if data.history:
            phase = "history"
            await progress(job_id, counts, phase=phase)
            params = {"downloadMedia": "false", "filter.timestamp.lte": int(until.timestamp())}
            if since:
                params["filter.timestamp.gte"] = int(since.timestamp())
            async for batch in pages(f"/api/{segment(waha_session)}/chats/all/messages", params):
                for payload in batch:
                    timestamp = payload.get("timestamp", 0)
                    if not isinstance(timestamp, (int, float)) or timestamp > until.timestamp() or (since and timestamp < since.timestamp()):
                        counts["skipped"] += 1
                    else:
                        counts["messages" if await import_message(payload, principal) else "skipped"] += 1
                    await progress(job_id, counts)
        await progress(job_id, counts, "completed")
    except asyncio.CancelledError:
        await progress(job_id, counts, "failed", "Sincronização interrompida. Execute novamente para continuar.")
        raise
    except Exception as error:
        from log import logger
        status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
        await logger.error("Sync", "Import", f"job={job_id} phase={phase} error={type(error).__name__} http_status={status}")
        stage = "os contatos" if phase == "contacts" else "o histórico"
        detail = f"O WhatsApp retornou HTTP {status}." if status else "Verifique a conexão do WhatsApp."
        try:
            await progress(job_id, counts, "failed", f"Não foi possível sincronizar {stage}. {detail} Tente novamente.", phase=phase)
        except RuntimeError:
            pass  # An expired job is already marked failed by another worker.
