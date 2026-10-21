"""Server-side WAHA management; provider credentials never reach the browser."""
from contextlib import asynccontextmanager
import asyncio

import httpx
from fastapi import HTTPException

from external.waha.base import request, segment, waha_api, waha_api_key, waha_session
from scripts.waha_session import configure_session, get_webhook_url
from utils import get_env_var


@asynccontextmanager
async def provider_errors():
    try:
        yield
    except httpx.HTTPStatusError as error:
        code = error.response.status_code
        if code == 404:
            raise HTTPException(409, "Inicie a conexão antes de solicitar o QR code ou código.") from None
        if code in (400, 409, 422):
            raise HTTPException(409, "A sessão ainda não está pronta. Atualize o estado e tente novamente.") from None
        raise HTTPException(502, "O WhatsApp não respondeu como esperado. Confira a configuração do WAHA.") from None
    except (httpx.RequestError, RuntimeError):
        raise HTTPException(502, "Não foi possível acessar o WAHA. Verifique se o serviço está em execução.") from None


async def connection_status() -> dict:
    async with provider_errors():
        try:
            result = await request("GET", f"/api/sessions/{segment(waha_session)}")
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            return {"session": waha_session, "status": "NOT_CREATED", "me": None}
    me = result.get("me") or {}
    principal = None
    if result.get("status") == "WORKING" and me:
        from services.setup import map_principal
        async with provider_errors():
            principal = await map_principal(me)
    return {"session": waha_session, "status": result.get("status", "UNKNOWN"),
            "me": {"id": me.get("id"), "name": me.get("pushName")} if me else None,
            "principal": principal}


async def start_connection() -> dict:
    async with provider_errors():
        await configure_session(get_webhook_url())
        return await connection_status()


async def qr_image() -> bytes:
    async with provider_errors():
        if not waha_api_key:
            raise RuntimeError("WAHA key not configured")
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{waha_api}/api/{segment(waha_session)}/auth/qr", headers={
                "X-Api-Key": waha_api_key, "Accept": "image/png",
            })
            response.raise_for_status()
        if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise HTTPException(502, "O WAHA não retornou um QR code válido.")
        return response.content


async def ensure_pairing_ready():
    current = await connection_status()
    if current["status"] in ("NOT_CREATED", "STOPPED", "FAILED"):
        current = await start_connection()
    for _ in range(20):
        if current["status"] == "SCAN_QR_CODE":
            return
        if current["status"] == "WORKING":
            raise HTTPException(409, "O WhatsApp já está conectado.")
        await asyncio.sleep(1)
        current = await connection_status()
    raise HTTPException(409, "O WhatsApp ainda está iniciando. Aguarde alguns instantes e tente gerar o código novamente.")


async def pairing_code(phone_number: str) -> dict:
    await ensure_pairing_ready()
    async with provider_errors():
        result = await request("POST", f"/api/{segment(waha_session)}/auth/request-code",
                               payload={"phoneNumber": phone_number.removeprefix("+")})
        code = result.get("code")
        if not isinstance(code, str) or not code.strip():
            raise HTTPException(502, "O WAHA não retornou um código de conexão.")
        return {"code": code.strip()}
