"""WAHA GOWS transport configuration and address conversion."""
from urllib.parse import quote

import httpx

from utils import get_env_var


waha_api = (get_env_var("WAHA_BASE_URL") or "http://waha:3000").rstrip("/")
waha_api_key = get_env_var("WAHA_API_KEY")
waha_session = get_env_var("WAHA_SESSION") or "default"


def segment(value: str) -> str:
    return quote(value, safe="")


def chat_id(value: str) -> str:
    if not value:
        raise ValueError("WhatsApp destination is required")
    value = value.removeprefix("+")
    if value.endswith("@s.whatsapp.net"):
        return value.replace("@s.whatsapp.net", "@c.us")
    if "@" in value:
        return value
    # Existing group/reminder callers pass bare group IDs.
    if "-" in value or (value.isdigit() and len(value) >= 16):
        return value + "@g.us"
    return value + "@c.us"


async def request(method: str, path: str, *, payload: dict | None = None,
                  params: dict | None = None, timeout: float = 60) -> dict:
    if not waha_api_key:
        raise RuntimeError("WAHA_API_KEY is required")
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(
            method, waha_api + path, json=payload, params=params,
            headers={"X-Api-Key": waha_api_key},
        )
        response.raise_for_status()
        return response.json() if response.content else {}
