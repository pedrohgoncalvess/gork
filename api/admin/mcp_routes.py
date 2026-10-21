from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from api.admin.auth import require_admin
from api.admin.router import get_db
from api.admin.store import get_entity
from database.models.base import User, Group
from database.models.manager import McpServer
from external.mcp_client import discover
from services.mcp_config import McpInput, decrypt_settings, encrypt_settings


router = APIRouter(prefix="/admin/api/mcps", tags=["Administration"], dependencies=[Depends(require_admin)])


def summary(item):
    return {key: getattr(item, key) for key in (
        "id", "name", "description", "url", "transport", "enabled", "tool_names", "tools",
        "timeout_seconds", "user_id", "group_id", "checked_at", "last_error",
    )}


async def existing(db, identifier, lock=False):
    item = await get_entity(db, McpServer, identifier, lock=lock)
    if item.deleted_at:
        raise HTTPException(404, "MCP não encontrado.")
    return item


async def save(db, data: McpInput, identifier=None):
    if data.user_id is not None:
        await get_entity(db, User, data.user_id)
    if data.group_id is not None:
        await get_entity(db, Group, data.group_id)
    try:
        encrypted = encrypt_settings(data)
    except ValueError as error:
        raise HTTPException(503, str(error)) from None
    item = await existing(db, identifier, lock=True) if identifier else McpServer(tools=[], tool_names=[])
    old = decrypt_settings(item.settings_encrypted) if identifier else {}
    connection_changed = any((getattr(item, "url", None) != data.url,
                              getattr(item, "transport", None) != data.transport,
                              old.get("headers") != data.headers, old.get("params") != data.params))
    for key, value in data.model_dump(exclude={"headers", "params", "fixed_arguments"}).items():
        setattr(item, key, value)
    item.settings_encrypted = encrypted
    if connection_changed:
        item.tools, item.checked_at, item.last_error = [], None, None
    elif item.tools:
        available = {tool["name"] for tool in item.tools}
        if set(data.tool_names) - available:
            raise HTTPException(422, "Há ferramentas não encontradas no catálogo. Teste o MCP antes de habilitá-las.")
    db.add(item)
    await db.commit()
    return {"id": item.id, "needs_sync": connection_changed}


@router.get("")
async def list_servers(db=Depends(get_db)):
    result = await db.execute(select(McpServer).where(McpServer.deleted_at.is_(None)).order_by(McpServer.id))
    return [summary(item) for item in result.scalars()]


@router.get("/{identifier}")
async def server_detail(identifier: int, db=Depends(get_db)):
    item = await existing(db, identifier)
    try:
        settings = decrypt_settings(item.settings_encrypted)
    except ValueError as error:
        raise HTTPException(503, str(error)) from None
    return {**summary(item), **settings}


@router.post("", status_code=201)
async def create_server(data: McpInput, db=Depends(get_db)):
    return await save(db, data)


@router.put("/{identifier}")
async def update_server(identifier: int, data: McpInput, db=Depends(get_db)):
    return await save(db, data, identifier)


@router.post("/{identifier}/sync")
async def sync_server(identifier: int, db=Depends(get_db)):
    item = await existing(db, identifier, lock=True)
    try:
        tools = await discover(item, decrypt_settings(item.settings_encrypted))
        if len({tool["name"] for tool in tools}) != len(tools):
            raise ValueError("Duplicate tool names")
        item.tools, item.last_error = tools, None
    except Exception:
        item.tools = []
        item.last_error = "Não foi possível consultar o catálogo. Confira URL, transporte, headers e parâmetros."
    item.checked_at = datetime.now(timezone.utc)
    await db.commit()
    if item.last_error:
        raise HTTPException(502, item.last_error)
    return {"tools": item.tools, "checked_at": item.checked_at}


@router.delete("/{identifier}")
async def delete_server(identifier: int, db=Depends(get_db)):
    item = await existing(db, identifier, lock=True)
    item.enabled, item.deleted_at = False, datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}
