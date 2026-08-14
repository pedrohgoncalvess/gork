from datetime import datetime

import httpx

from log import openrouter_logger
from utils import get_env_var


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


def _payload_for_log(payload: dict) -> dict:
    """Return a copy safe for logs, replacing image data with a counter."""
    image_count = 0
    sanitized_payload = dict(payload)
    sanitized_messages = []

    for message in payload.get("messages", []):
        if not isinstance(message, dict):
            sanitized_messages.append(message)
            continue

        sanitized_message = dict(message)
        content = message.get("content")
        if isinstance(content, list):
            sanitized_content = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_count += 1
                    continue
                sanitized_content.append(item)
            sanitized_message["content"] = sanitized_content

        sanitized_messages.append(sanitized_message)

    if "messages" in payload:
        sanitized_payload["messages"] = sanitized_messages

    input_references = payload.get("input_references")
    if isinstance(input_references, list):
        image_count += len(input_references)
        sanitized_payload.pop("input_references", None)

    sanitized_payload["image_count"] = image_count
    return sanitized_payload


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

    log_payload = _payload_for_log(payload)

    async with httpx.AsyncClient(timeout=120) as client:
        duration = datetime.now() - start
        try:
            response = await client.post(f"{OPENROUTER_ENDPOINT}/chat/completions", json=payload, headers=headers)
            if response.status_code >= 400:
                minutes = duration.total_seconds() / 60
                await openrouter_logger.error(
                    "OpenRouter",
                    f"HTTPError_{response.status_code}",
                    f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Status: {response.status_code}. Response: {response.text}. Payload: {log_payload}"
                )
            response.raise_for_status()
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info("OpenRouter", "Conversation", f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Payload: {log_payload}")
            return response.json()
        except Exception as error:
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info(
                "OpenRouter",
                "Conversation",
                f"Model: {payload.get('model')} - Time took: {minutes:.2f}. Payload: {log_payload}. Error: {error}"
            )
            raise error


async def generate_images(payload: dict) -> dict:
    start = datetime.now()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}",
    }
    log_payload = _payload_for_log(payload)

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(
                f"{OPENROUTER_ENDPOINT}/images",
                json=payload,
                headers=headers,
            )
            duration = datetime.now() - start
            minutes = duration.total_seconds() / 60
            if response.status_code >= 400:
                await openrouter_logger.error(
                    "OpenRouter",
                    f"ImageHTTPError_{response.status_code}",
                    f"Model: {payload.get('model')} - Time took: {minutes:.2f}. "
                    f"Status: {response.status_code}. Response: {response.text}. "
                    f"Payload: {log_payload}",
                )
            response.raise_for_status()
            await openrouter_logger.info(
                "OpenRouter",
                "ImageGeneration",
                f"Model: {payload.get('model')} - Time took: {minutes:.2f}. "
                f"Payload: {log_payload}",
            )
            return response.json()
        except Exception as error:
            duration = datetime.now() - start
            minutes = duration.total_seconds() / 60
            await openrouter_logger.info(
                "OpenRouter",
                "ImageGeneration",
                f"Model: {payload.get('model')} - Time took: {minutes:.2f}. "
                f"Payload: {log_payload}. Error: {error}",
            )
            raise


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
