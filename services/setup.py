from security.crypto import encrypt, decrypt
"""Database-backed runtime settings and automatic WAHA account discovery."""
import re
import httpx

from sqlalchemy import text

from database import PgConnection
from database.operations.base import UserRepository
from external.waha.base import request, segment, waha_session


def address_part(value, suffixes):
    if not isinstance(value, str):
        return None
    for suffix in suffixes:
        if value.endswith(suffix):
            part = value.removesuffix(suffix).split(":")[0]
            return part if part.isdigit() else None
    return None


async def settings(db=None):
    if db is None:
        async with PgConnection() as session:
            return await settings(session)
    row = (await db.execute(text("SELECT * FROM base.app_settings WHERE id = 1"))).mappings().one()
    return {key: decrypt(value, "identity") if key in ("phone_number", "lid", "test_number") else value
            for key, value in row.items()}


async def map_principal(me):
    phone = address_part(me.get("id"), ("@c.us", "@s.whatsapp.net"))
    lid = address_part(me.get("lid"), ("@lid",))
    if not phone:
        return None
    if not lid:
        try:
            result = await request("GET", f"/api/{segment(waha_session)}/lids/pn/{segment(phone + '@c.us')}")
            lid = address_part(result.get("lid"), ("@lid",))
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
    async with PgConnection() as db:
        # Serialize account reconciliation across Gunicorn workers.
        await db.execute(text("SELECT id FROM base.app_settings WHERE id = 1 FOR UPDATE"))
        user = await UserRepository(db).find_or_create(
            lid=lid or phone, phone_number=phone, name=me.get("pushName") or me.get("name") or "Gork")
        await db.execute(text("""UPDATE base.app_settings SET principal_user_id=:user,
            phone_number=:phone, lid=:lid WHERE id=1"""), {"user": user.id, "phone": encrypt(phone, "identity", True), "lid": encrypt(lid, "identity", True)})
        await db.commit()
        return {"user_id": user.id, "phone_number": phone, "lid": lid}


async def discover_principal():
    session = await request("GET", f"/api/sessions/{segment(waha_session)}")
    if session.get("status") == "WORKING" and session.get("me"):
        return await map_principal(session["me"])
    return None


async def save_test_settings(test_mode, test_number, db):
    number = test_number.removeprefix("+") if test_number else None
    if test_mode and (not number or not re.fullmatch(r"[1-9]\d{6,14}", number)):
        raise ValueError("Informe um número de teste válido antes de ativar o modo de teste.")
    await db.execute(text("UPDATE base.app_settings SET test_mode=:mode, test_number=:number WHERE id=1"),
                     {"mode": test_mode, "number": encrypt(number, "identity", True)})
    await db.commit()
    from services.ban_cache import invalidate
    await invalidate()
    return await settings(db)


_configured = False


async def automate_setup():
    """Retry unavailable WAHA on the next scheduler tick without blocking startup."""
    global _configured
    from scripts.waha_session import configure_session, get_webhook_url
    from log import logger
    try:
        if not _configured:
            await configure_session(get_webhook_url())
            _configured = True
        await discover_principal()
    except Exception as error:
        await logger.warn("Setup", "WAHA", f"Setup pendente; nova tentativa automática ({type(error).__name__}).")
