from datetime import datetime

import httpx

from log import openrouter_logger
from utils import get_env_var


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"

async def completions(payload: dict, is_online: bool = False) -> dict:
    start = datetime.now()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}",
    }

    if is_online:
        tools = payload.get("tools", [])
        if not any(t.get("type") == "openrouter:web_search" for t in tools if isinstance(t, dict)):
            payload = {**payload, "tools": tools + [{"type": "openrouter:web_search"}]}

    async with httpx.AsyncClient(timeout=120) as client:
        duration = datetime.now() - start
        try:
            response = await client.post(f"{OPENROUTER_ENDPOINT}/chat/completions", json=payload, headers=headers)
            if response.status_code >= 400:
                minutes = duration.total_seconds() / 60
                await openrouter_logger.error(
                    "OpenRouter",
                    f"HTTPError_{response.status_code}",
                    f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Status: {response.status_code}. Response: {response.text}. Payload: {payload}"
                )
            response.raise_for_status()
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info("OpenRouter", "Conversation", f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Payload: {payload}")
            return response.json()
        except Exception as error:
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info(
                "OpenRouter",
                "Conversation",
                f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Payload: {payload}. Error: {error}"
            )
            raise error


async def embeddings(text: str, model: str) -> dict:
    start = datetime.now()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}",
    }

    payload = {
      "model": model,
      "input": text,
      "encodingFormat": "float"
    }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(f"{OPENROUTER_ENDPOINT}/embeddings", json=payload, headers=headers)
            response.raise_for_status()
            duration = datetime.now() - start
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info("OpenRouter", "Embedding", f"Model: {payload.get('model')} - Time took: {minutes:.2f}")
            return response.json()
        except Exception as error:
            duration = datetime.now() - start
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info(
                "OpenRouter",
                "Conversation",
                f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Payload: {payload}. Error: {error}"
            )
            raise error
