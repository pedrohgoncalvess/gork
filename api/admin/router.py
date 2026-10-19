from datetime import datetime, timezone
import secrets
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError

from api.admin import connection, store
from api.admin.auth import COOKIE_NAME, SESSION_SECONDS, create_session, csrf_token, password, require_admin
from api.admin.schemas import (AgentInput, BlacklistInput, CommandInput, GroupInput, GroupSettings,
                               Login, ModelInput, OverrideInput, PairingCode, UserInput, WhitelistInput)
from database import PgConnection
from database.models.base import BlackList, Group, User, WhiteList
from database.models.manager import Agent, DisabledCommand, Model, ModelConversation
from database.operations.base import GroupRepository, UserRepository
from external.waha.base import request as waha_request, segment, waha_session
from agents.init import init_agents


STATIC_DIR = Path(__file__).parent / "static"
router = APIRouter(prefix="/admin", tags=["Administration"])
api = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])


async def get_db():
    async with PgConnection() as db:
        try:
            yield db
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Já existe um registro com esse identificador.") from None
        except OperationalError:
            await db.rollback()
            raise HTTPException(503, "O banco de dados está indisponível. Tente novamente.") from None


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def panel():
    return FileResponse(STATIC_DIR / "index.html", headers={
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    })


@router.post("/api/login")
async def login(data: Login, request: Request):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Origem inválida.")
    if not secrets.compare_digest(data.password.encode(), password().encode()):
        raise HTTPException(401, "Senha incorreta.")
    session = create_session()
    response = JSONResponse({"csrf_token": csrf_token(session)}, headers={"Cache-Control": "no-store"})
    response.set_cookie(COOKIE_NAME, session, max_age=SESSION_SECONDS, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/admin")
    return response


@api.get("/session")
async def session(session: str = Depends(require_admin)):
    return JSONResponse({"csrf_token": csrf_token(session)}, headers={"Cache-Control": "no-store"})


@api.post("/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/admin")
    return response


@api.get("/connection")
async def status():
    return JSONResponse(await connection.connection_status(), headers={"Cache-Control": "no-store"})


@api.post("/connection/start")
async def start():
    return await connection.start_connection()


@api.get("/connection/qr")
async def qr():
    return Response(await connection.qr_image(), media_type="image/png", headers={"Cache-Control": "no-store"})


@api.post("/connection/code")
async def code(data: PairingCode):
    return JSONResponse(await connection.pairing_code(data.phone_number), headers={"Cache-Control": "no-store"})


@api.get("/overview")
async def overview(db=Depends(get_db)):
    counts = {}
    for key, model, filters in (
        ("users", User, []), ("groups", Group, []), ("agents", Agent, []),
        ("allowed", WhiteList, [WhiteList.deleted_at.is_(None)]),
        ("blocked", BlackList, [BlackList.deleted_at.is_(None)]),
    ):
        counts[key] = await db.scalar(select(func.count()).select_from(model).where(*filters))
    return counts


@api.get("/directory/{kind}")
async def directory(kind: Literal["user", "group"], q: str = Query("", max_length=100),
                    offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), db=Depends(get_db)):
    return await store.directory(db, kind, q, offset, limit)


@api.post("/users", status_code=201)
async def create_user(data: UserInput, db=Depends(get_db)):
    phone = data.phone_number.removeprefix("+") if data.phone_number else None
    lid = data.lid.removesuffix("@lid") if data.lid else phone
    item = await UserRepository(db).find_or_create(lid=lid, phone_number=phone, name=data.name)
    return {"id": item.id}


@api.post("/groups", status_code=201)
async def create_group(data: GroupInput, db=Depends(get_db)):
    item = await GroupRepository(db).find_or_create(group_jid=data.group_jid.removesuffix("@g.us"), name=data.name)
    return {"id": item.id}


@api.post("/groups/sync")
async def sync_groups(db=Depends(get_db)):
    async with connection.provider_errors():
        payload = await waha_request("GET", f"/api/{segment(waha_session)}/groups")
    entries = payload if isinstance(payload, list) else [dict(value, id=value.get("id") or key)
        for key, value in payload.items() if isinstance(value, dict)]
    imported = 0
    for entry in entries:
        identifier = entry.get("id") or entry.get("JID")
        if not isinstance(identifier, str) or not identifier.endswith("@g.us"):
            continue
        name = entry.get("subject") or entry.get("Name") or entry.get("name") or (entry.get("GroupName") or {}).get("Name")
        await GroupRepository(db).find_or_create(group_jid=identifier.removesuffix("@g.us"), name=name)
        imported += 1
    return {"imported": imported}


@api.put("/whitelist/{kind}/{identifier}")
async def whitelist(kind: Literal["user", "group"], identifier: int, data: WhitelistInput, db=Depends(get_db)):
    return await store.set_whitelist(db, kind, identifier, data.allowed, data.is_admin)


@api.patch("/groups/{identifier}")
async def group_settings(identifier: int, data: GroupSettings, db=Depends(get_db)):
    item = await store.get_entity(db, Group, identifier, lock=True)
    item.auto_message = data.auto_message
    await db.commit()
    return {"auto_message": item.auto_message}


@api.get("/blacklist")
async def blacklist(db=Depends(get_db)):
    result = await db.execute(select(BlackList.id, BlackList.user_id, BlackList.features,
                                    User.name, User.phone_number, User.src_id).join(User, User.id == BlackList.user_id)
                              .where(BlackList.deleted_at.is_(None)).order_by(BlackList.id.desc()))
    return [dict(row) for row in result.mappings()]


@api.put("/blacklist")
async def save_blacklist(data: BlacklistInput, db=Depends(get_db)):
    return await store.save_blacklist(db, data)


@api.delete("/blacklist/{user_id}")
async def remove_blacklist(user_id: int, db=Depends(get_db)):
    await store.get_entity(db, User, user_id, lock=True)
    rows = (await db.execute(select(BlackList).where(BlackList.user_id == user_id, BlackList.deleted_at.is_(None)))).scalars().all()
    for row in rows:
        row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


@api.get("/agents")
async def agents(db=Depends(get_db)):
    result = await db.execute(select(Agent.id, Agent.name, Agent.prompt, Agent.model_id,
                                    Agent.model_managed, Agent.prompt_managed, Model.name.label("model_name"),
                                    Model.openrouter_id).join(Model, Model.id == Agent.model_id).order_by(Agent.name))
    return [dict(row) for row in result.mappings()]


@api.patch("/agents/{identifier}")
async def save_agent(identifier: int, data: AgentInput, db=Depends(get_db)):
    return await store.save_agent(db, identifier, data)


@api.post("/agents/{identifier}/reset")
async def reset_agent(identifier: int, db=Depends(get_db)):
    agent = await store.get_entity(db, Agent, identifier, lock=True)
    agent.model_managed, agent.prompt_managed = False, False
    await db.commit()
    await init_agents()
    return {"ok": True}


@api.get("/models")
async def models(db=Depends(get_db)):
    result = await db.execute(select(Model.id, Model.name, Model.openrouter_id).order_by(Model.name, Model.id))
    return [dict(row) for row in result.mappings()]


@api.post("/models", status_code=201)
async def create_model(data: ModelInput, db=Depends(get_db)):
    existing = await db.scalar(select(Model).where(Model.openrouter_id == data.openrouter_id).limit(1))
    if existing:
        raise HTTPException(409, "Esse modelo já está cadastrado.")
    item = Model(**data.model_dump())
    db.add(item)
    await db.commit()
    return {"id": item.id}


@api.get("/overrides")
async def overrides(db=Depends(get_db)):
    result = await db.execute(select(ModelConversation.id, ModelConversation.agent_id,
        ModelConversation.model_id, ModelConversation.user_id, ModelConversation.group_id,
        Agent.name.label("agent_name"), Model.openrouter_id, User.name.label("user_name"), Group.name.label("group_name"))
        .join(Agent, Agent.id == ModelConversation.agent_id).join(Model, Model.id == ModelConversation.model_id)
        .outerjoin(User, User.id == ModelConversation.user_id).outerjoin(Group, Group.id == ModelConversation.group_id)
        .order_by(ModelConversation.id.desc()))
    return [dict(row) for row in result.mappings()]


@api.post("/overrides")
async def save_override(data: OverrideInput, db=Depends(get_db)):
    return await store.save_override(db, data)


@api.delete("/overrides/{identifier}")
async def remove_override(identifier: int, db=Depends(get_db)):
    await store.remove_override(db, identifier)
    return {"ok": True}


@api.get("/commands")
async def commands(db=Depends(get_db)):
    result = await db.execute(select(DisabledCommand.id, DisabledCommand.command, DisabledCommand.user_id,
        DisabledCommand.group_id, DisabledCommand.message, DisabledCommand.disabled_until,
        User.name.label("user_name"), Group.name.label("group_name"))
        .outerjoin(User, User.id == DisabledCommand.user_id).outerjoin(Group, Group.id == DisabledCommand.group_id)
        .where(DisabledCommand.deleted_at.is_(None)).order_by(DisabledCommand.id.desc()))
    return {"catalog": store.commands_catalog(), "rules": [dict(row) for row in result.mappings()]}


@api.post("/commands", status_code=201)
async def create_command(data: CommandInput, db=Depends(get_db)):
    return await store.save_command(db, data)


@api.put("/commands/{identifier}")
async def update_command(identifier: int, data: CommandInput, db=Depends(get_db)):
    return await store.save_command(db, data, identifier)


@api.delete("/commands/{identifier}")
async def remove_command(identifier: int, db=Depends(get_db)):
    row = await store.get_entity(db, DisabledCommand, identifier, lock=True)
    row.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


router.include_router(api)
