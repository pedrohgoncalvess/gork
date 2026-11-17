"""Client for the trapo generator API (two-band football banner images).

The API takes the raw chat message: it drops mentions and the !trapo trigger,
reads `:time=<team>` and splits the phrase between the two bands by itself.
"""

import httpx

from utils import get_env_var


DEFAULT_TRAPO_API_URL = "https://trapo-generator-zeta.vercel.app/api/trapo"


class TrapoError(Exception):
    """Request rejected by the API; the message is safe to show in the chat."""


async def generate_trapo(command: str, phrase: str | None = None) -> bytes:
    payload = {"cmd": command}
    if phrase:
        payload["frase"] = phrase

    url = get_env_var("TRAPO_API_URL") or DEFAULT_TRAPO_API_URL
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, json=payload)

    if response.status_code == 400:
        raise TrapoError(response.json().get("error") or "Não consegui gerar o trapo.")
    response.raise_for_status()
    return response.content
