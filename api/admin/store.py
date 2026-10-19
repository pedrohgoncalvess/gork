from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select

from database.models.base import BlackList, Group, User, WhiteList
from database.models.manager import Agent, DisabledCommand, Model, ModelConversation
from database.operations.base import BlackListRepository
from database.operations.manager import ModelConversationRepository
from database.operations.manager.disabled_command import normalize_command
from api.routes.webhook.waha.handles.core import COMMANDS


def commands_catalog() -> list[dict]:
    commands = {normalize_command(item[0]): item[1].split(" _[")[0]
                for item in COMMANDS if item[0].startswith("!") and item[2] != "hidden"}
    commands["interaction"] = "Conversas e respostas do Gork"
    return [{"id": name, "description": description} for name, description in sorted(commands.items())]


def valid_command(value: str) -> str:
    value = normalize_command(value)
    if value not in {item["id"] for item in commands_catalog()}:
        raise HTTPException(422, "Selecione um comando válido.")
    return value


async def get_entity(db, model, identifier: int, *, lock=False):
    statement = select(model).where(model.id == identifier)
    if lock:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(404, "Registro não encontrado.")
    return item


async def directory(db, kind: str, q: str, offset: int, limit: int) -> dict:
    model = User if kind == "user" else Group
    active = (WhiteList.sender_type == kind, WhiteList.sender_id == model.id, WhiteList.deleted_at.is_(None))
    allowed = select(func.count(WhiteList.id)).where(*active).correlate(model).scalar_subquery() > 0
    admin = select(func.count(WhiteList.id)).where(*active, WhiteList.is_admin.is_(True)).correlate(model).scalar_subquery() > 0
    columns = [model.id, model.name, model.src_id, allowed.label("allowed"), admin.label("is_admin")]
    if kind == "user":
        blocked = select(func.count(BlackList.id)).where(BlackList.user_id == User.id, BlackList.deleted_at.is_(None)).correlate(User).scalar_subquery() > 0
        columns += [User.phone_number, blocked.label("blocked")]
    else:
        columns += [Group.auto_message]
    filters = []
    if q:
        fields = [model.name, model.src_id] + ([User.phone_number] if kind == "user" else [])
        filters.append(or_(*(field.ilike(f"%{q}%") for field in fields)))
    total = await db.scalar(select(func.count()).select_from(model).where(*filters))
    result = await db.execute(select(*columns).where(*filters).order_by(model.name.asc().nullslast(), model.id).offset(offset).limit(limit))
    return {"items": [dict(row) for row in result.mappings()], "total": total, "offset": offset, "limit": limit}


async def set_whitelist(db, kind: str, identifier: int, allowed: bool, is_admin: bool):
    await get_entity(db, User if kind == "user" else Group, identifier, lock=True)
    rows = (await db.execute(select(WhiteList).where(
        WhiteList.sender_type == kind, WhiteList.sender_id == identifier, WhiteList.deleted_at.is_(None)
    ).order_by(WhiteList.id))).scalars().all()
    if allowed:
        entry = rows[0] if rows else WhiteList(sender_type=kind, sender_id=identifier)
        entry.is_admin = is_admin
        db.add(entry)
        rows = rows[1:]
    for entry in rows:
        entry.deleted_at = datetime.now()
    await db.commit()
    return {"allowed": allowed, "is_admin": bool(allowed and is_admin)}


async def save_blacklist(db, data):
    await get_entity(db, User, data.user_id, lock=True)
    features = sorted({BlackListRepository.normalize_feature(value) for value in data.features})
    for feature in features:
        valid_command(feature)
    repo = BlackListRepository(db)
    entry = await repo.get_active(data.user_id)
    if entry is None:
        entry = BlackList(user_id=data.user_id, features=features)
        db.add(entry)
    else:
        entry.features = features
    await db.commit()
    return {"user_id": data.user_id, "features": features}


async def save_agent(db, identifier: int, data):
    agent = await get_entity(db, Agent, identifier, lock=True)
    if data.model_id is not None:
        await get_entity(db, Model, data.model_id)
        agent.model_id, agent.model_managed = data.model_id, True
    if data.prompt is not None:
        agent.prompt, agent.prompt_managed = data.prompt, True
    await db.commit()
    return {"id": agent.id, "model_id": agent.model_id}


async def save_override(db, data):
    await get_entity(db, Agent, data.agent_id, lock=True)
    await get_entity(db, Model, data.model_id)
    if data.user_id is not None:
        await get_entity(db, User, data.user_id)
    else:
        await get_entity(db, Group, data.group_id)
    repo = ModelConversationRepository(db)
    if data.group_id is not None:
        result = await repo.upsert_for_group(data.group_id, data.agent_id, data.model_id)
    else:
        result = await repo.upsert_for_user(data.user_id, data.agent_id, data.model_id)
    return {"id": result.id}


async def remove_override(db, identifier: int):
    item = await get_entity(db, ModelConversation, identifier)
    await get_entity(db, Agent, item.agent_id, lock=True)
    # Older rows must not become effective again when the latest override is removed.
    await db.execute(delete(ModelConversation).where(
        ModelConversation.agent_id == item.agent_id,
        ModelConversation.user_id == item.user_id,
        ModelConversation.group_id == item.group_id,
    ))
    await db.commit()


async def save_command(db, data, identifier=None):
    command = valid_command(data.command)
    if data.user_id is not None:
        await get_entity(db, User, data.user_id)
    if data.group_id is not None:
        await get_entity(db, Group, data.group_id)
    item = await get_entity(db, DisabledCommand, identifier, lock=True) if identifier else DisabledCommand()
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    item.command = command
    db.add(item)
    await db.commit()
    return {"id": item.id}
