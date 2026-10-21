"""Authenticated browsing and semantic search of stored conversation data."""
import asyncio
import mimetypes
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import aliased

from api.admin.dependencies import get_db
from database.models.base import Group, User
from database.models.content import Media, Message
from database.operations.manager import ModelRepository
from embeddings.generate_embeddings import fit_embedding
from external.openrouter import embeddings
from s3 import S3Client

router = APIRouter()


def utc_naive(value):
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(422, "Informe as datas com fuso horário.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


async def vectors(db, texts):
    model = await ModelRepository(db).get_default_embedding_model()
    if not model:
        raise HTTPException(503, "Configure um modelo de embeddings para usar a busca semântica.")
    try:
        payload = await embeddings(texts, model.openrouter_id)
        rows = sorted(payload["data"], key=lambda row: row["index"])
        if len(rows) != len(texts) or any(not row["embedding"] for row in rows):
            raise ValueError("Invalid embedding response")
        return [fit_embedding(row["embedding"]) for row in rows]
    except Exception:
        raise HTTPException(503, "A busca semântica está indisponível. Tente novamente.") from None


@router.get("/data/{kind}")
async def browse(kind: str, group_id: int | None = Query(None, gt=0),
                 user_id: int | None = Query(None, gt=0), start: datetime | None = None,
                 end: datetime | None = None, q: str = Query("", max_length=2000),
                 index_messages: bool = False,
                 offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), db=Depends(get_db)):
    if kind not in {"attachments", "messages"}:
        raise HTTPException(404, "Visualização não encontrada.")
    start, end = utc_naive(start), utc_naive(end)
    if start and end and start >= end:
        raise HTTPException(422, "O fim do período deve ser posterior ao início.")
    filters = [Message.deleted_at.is_(None)]
    if group_id:
        filters.append(Message.group_id == group_id)
    if user_id:
        filters.append(or_(Message.user_id == user_id, Message.chat_user_id == user_id))
    if start:
        filters.append(Message.created_at >= start)
    if end:
        filters.append(Message.created_at < end)
    if kind == "attachments":
        filters.append(Media.id.is_not(None))
    remaining = 0
    distance = None
    q = q.strip()
    if q:
        query_vector = (await vectors(db, [q]))[0]
        if kind == "messages":
            missing = [*filters, Message.content.is_not(None), func.length(func.trim(Message.content)) > 0,
                       Message.content_embedding.is_(None)]
            pending = (await db.execute(select(Message.id, Message.content).outerjoin(Media, Media.id == Message.media_id)
                       .where(*missing).order_by(Message.id).limit(100))).all() if index_messages else []
            if pending:
                indexed = await vectors(db, [row.content for row in pending])
                for row, vector in zip(pending, indexed):
                    await db.execute(update(Message).where(Message.id == row.id, Message.content == row.content)
                                     .values(content_embedding=vector))
                await db.commit()
            remaining = await db.scalar(select(func.count()).select_from(Message)
                         .outerjoin(Media, Media.id == Message.media_id).where(*missing))
            distance = Message.content_embedding.cosine_distance(query_vector)
            filters.append(Message.content_embedding.is_not(None))
        else:
            distance = Media.description_embedding.cosine_distance(query_vector)
            filters.append(Media.description_embedding.is_not(None))
    contact = aliased(User)
    statement = select(Message.id, Message.content, Message.created_at, Message.user_id, Message.group_id,
        User.name.label("user_name"), User.phone_number, Group.name.label("group_name"),
        contact.name.label("contact_name"), Message.chat_user_id, Media.id.label("media_id"),
        Media.name.label("media_name"), Media.type.label("media_type"), Media.size,
        Media.description).select_from(Message).outerjoin(User, User.id == Message.user_id)\
        .outerjoin(Group, Group.id == Message.group_id).outerjoin(contact, contact.id == Message.chat_user_id)\
        .outerjoin(Media, Media.id == Message.media_id).where(*filters)
    total = await db.scalar(select(func.count()).select_from(statement.subquery()))
    if distance is not None:
        statement = statement.add_columns((1 - distance).label("similarity")).order_by(distance, Message.id.desc())
    else:
        statement = statement.order_by(Message.created_at.desc(), Message.id.desc())
    result = await db.execute(statement.offset(offset).limit(limit))
    items = []
    for row in result.mappings():
        item = dict(row)
        item["created_at"] = row["created_at"].replace(tzinfo=timezone.utc).isoformat()
        item["size"] = float(row["size"]) if row["size"] is not None else None
        item["media_url"] = f"/admin/api/media/{row['media_id']}" if row["media_id"] else None
        items.append(item)
    return JSONResponse({"items": items, "total": total, "offset": offset, "limit": limit,
                         "indexing_remaining": remaining}, headers={"Cache-Control": "no-store"})


@router.get("/media/{identifier}")
async def media(identifier: int, download: bool = False, db=Depends(get_db)):
    item = await db.scalar(select(Media).where(Media.id == identifier,
        select(Message.id).where(Message.media_id == Media.id, Message.deleted_at.is_(None)).exists()))
    if item is None:
        raise HTTPException(404, "Anexo não encontrado.")
    client = S3Client()
    try:
        await client.connect()
        response = await asyncio.to_thread(client.client.get_object, item.bucket, item.path.lstrip("/"))
    except Exception:
        raise HTTPException(503, "Não foi possível abrir o anexo.") from None
    mime = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
    # Only browser media formats may render inline; documents always download.
    inline = not download and mime.startswith(("image/", "audio/", "video/")) and mime != "image/svg+xml"

    def chunks():
        try:
            yield from response.stream(64 * 1024)
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(chunks(), media_type=mime, headers={
        "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(item.name, safe='')}",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
