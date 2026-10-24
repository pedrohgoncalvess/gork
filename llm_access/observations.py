"""Conversation-scoped notes, exposed through Gork's database tool calls."""

from typing import Any

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import cast, desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.manager import Observation
from database.operations.manager import ModelRepository
from embeddings import generate_text_embeddings


DEFAULT_OBSERVATION_LIMIT = 10
MAX_OBSERVATION_LIMIT = 50
MAX_OBSERVATION_LENGTH = 4000


def _scope(group_id: int | None, user_id: int):
    # Scope always comes from the current conversation, never from model parameters.
    if group_id is not None:
        return (Observation.group_id == group_id,)
    if user_id is None:
        raise ValueError("A private conversation requires a user_id")
    return (Observation.group_id.is_(None), Observation.user_id == user_id)


def _scoped(stmt, group_id, user_id):
    scope = _scope(group_id, user_id)
    return stmt.where(*scope)


def _serialize(note: Observation) -> dict[str, Any]:
    return {
        "id": note.id,
        "content": note.content,
        "source_message_id": note.source_message_id,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "embedding_indexed": note.embedding_model_id is not None,
    }


async def _embedding(db, text, user_id, group_id):
    model = await ModelRepository(db).get_default_embedding_model()
    if model is None:
        return None, None
    vector = await generate_text_embeddings(
        text, db=db, user_id=user_id, group_id=group_id, embedding_model=model,
    )
    # Zero vectors have no cosine similarity and are not indexed by HNSW.
    if not vector or not any(vector):
        return None, None
    return vector, model.id


async def save_observation(
        db: AsyncSession,
        group_id: int | None,
        user_id: int,
        content: str,
        source_message_id: int | None = None,
) -> dict[str, Any]:
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= MAX_OBSERVATION_LENGTH:
        raise ValueError("content must contain between 1 and 4000 characters")
    content = content.strip()
    existing = await db.execute(_scoped(
        select(Observation).where(Observation.content == content), group_id, user_id,
    ))
    note = existing.scalar_one_or_none()
    if note is not None and note.embedding_model_id is not None:
        return {**_serialize(note), "already_saved": True}

    vector, model_id = await _embedding(db, content, user_id, group_id)
    if note is not None:
        note.embedding = vector
        note.embedding_model_id = model_id
        await db.commit()
        await db.refresh(note)
        return {**_serialize(note), "already_saved": True}

    result = await db.execute(insert(Observation).values(
        group_id=group_id,
        user_id=user_id if group_id is None else None,
        source_message_id=source_message_id,
        content=content,
        embedding=vector,
        embedding_model_id=model_id,
    ).on_conflict_do_nothing().returning(Observation))
    note = result.scalar_one_or_none()
    await db.commit()
    if note is None:
        result = await db.execute(_scoped(
            select(Observation).where(Observation.content == content), group_id, user_id,
        ))
        note = result.scalar_one()
    return _serialize(note)


async def search_observations(
        db: AsyncSession,
        group_id: int | None,
        user_id: int,
        query: str | None = None,
        mode: str = "hybrid",
        limit: int | None = None,
) -> dict[str, Any]:
    if mode not in {"term", "similarity", "hybrid"}:
        raise ValueError("mode must be term, similarity, or hybrid")
    if query is not None and not isinstance(query, str):
        raise ValueError("query must be a string")
    query = (query or "").strip()
    if len(query) > MAX_OBSERVATION_LENGTH:
        raise ValueError("query must contain at most 4000 characters")
    limit = DEFAULT_OBSERVATION_LIMIT if limit is None else max(1, min(int(limit), MAX_OBSERVATION_LIMIT))
    base = _scoped(select(Observation), group_id, user_id)
    if not query:
        result = await db.execute(base.order_by(desc(Observation.created_at), desc(Observation.id)).limit(limit))
        return {"observations": [_serialize(note) for note in result.scalars().all()], "mode": "recent"}

    rankings = []
    if mode in {"term", "hybrid"}:
        # Only scoped notes enter memory; encrypted text cannot use SQL full-text indexes.
        result = await db.execute(base.order_by(desc(Observation.id)))
        needle = query.casefold()
        rankings.append([note for note in result.scalars().all()
                         if needle in note.content.casefold()][:limit])

    semantic_available = None
    if mode in {"similarity", "hybrid"}:
        vector, model_id = await _embedding(db, query, user_id, group_id)
        semantic_available = vector is not None
        if vector is not None:
            distance = cast(Observation.embedding, HALFVEC(2560)).cosine_distance(vector)
            result = await db.execute(base.where(
                Observation.embedding.is_not(None),
                Observation.embedding_model_id == model_id,
            ).order_by(distance).limit(limit))
            rankings.append(list(result.scalars().all()))

    # Reciprocal rank fusion keeps text and semantic results on comparable scales.
    scores, notes = {}, {}
    for ranking in rankings:
        for rank, note in enumerate(ranking, 1):
            notes[note.id] = note
            scores[note.id] = scores.get(note.id, 0) + 1 / (60 + rank)
    ordered = sorted(notes, key=lambda note_id: (-scores[note_id], -note_id))[:limit]
    return {
        "observations": [{**_serialize(notes[note_id]), "score": scores[note_id]} for note_id in ordered],
        "mode": mode,
        "semantic_available": semantic_available,
    }
