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

    if is_online and payload.get("model") and not payload["model"].endswith(":online"):
        payload = {**payload, "model": f"{payload['model']}:online"}

    with httpx.Client(timeout=120) as client:
        duration = datetime.now() - start
        try:
            response = client.post(f"{OPENROUTER_ENDPOINT}/chat/completions", json=payload, headers=headers)
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

    with httpx.Client(timeout=120) as client:
        try:
            response = client.post(f"{OPENROUTER_ENDPOINT}/embeddings", json=payload, headers=headers)
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
