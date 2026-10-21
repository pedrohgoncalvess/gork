import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response

from utils import get_env_var


COOKIE_NAME = "gork_admin"
SESSION_SECONDS = 12 * 60 * 60


def password() -> str:
    value = get_env_var("ADMIN_PASSWORD")
    if not value:
        raise HTTPException(503, "Configure ADMIN_PASSWORD no ambiente do Gork para acessar o painel.")
    return value


def signature(value: str) -> str:
    key = (get_env_var("ADMIN_SESSION_SECRET") or password()).encode()
    # Changing the login password also invalidates existing sessions.
    key = hashlib.sha256(key + password().encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def create_session() -> str:
    value = f"{int(time.time()) + SESSION_SECONDS}.{secrets.token_hex(16)}"
    return f"{value}.{signature(value)}"


def csrf_token(session: str) -> str:
    return signature("csrf:" + session)


async def require_admin(request: Request, response: Response) -> str:
    response.headers["Cache-Control"] = "no-store"
    session = request.cookies.get(COOKIE_NAME, "")
    try:
        expiry, nonce, supplied = session.split(".")
        valid = int(expiry) > time.time() and hmac.compare_digest(supplied, signature(f"{expiry}.{nonce}"))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(401, "Entre no painel para continuar.")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", "").encode(), csrf_token(session).encode()):
            raise HTTPException(403, "Sessão inválida. Atualize a página e tente novamente.")
    return session
