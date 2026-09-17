import asyncio
import json
from datetime import datetime

import httpx

from log import openrouter_logger
from utils import get_env_var


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1"


class OpenRouterVideoError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        provider_code: str | None = None,
    ):
        self.status_code = status_code
        self.provider_code = provider_code
        self.provider_message = message
        super().__init__(
            f"OpenRouter video request failed with HTTP {status_code}"
            + (f" ({provider_code})" if provider_code else "")
            + f": {message}"
        )


def _video_error_details(response: httpx.Response) -> tuple[str | None, str]:
    try:
        payload = response.json()
    except ValueError:
        return None, response.text[:2000]

    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    message = str(message or response.text[:2000])

    # Providers sometimes serialize their own JSON error inside OpenRouter's
    # message, prefixed by e.g. "HTTP 400: ". Recover its stable error code.
    nested_start = message.find("{")
    if nested_start >= 0:
        try:
            nested_payload = json.loads(message[nested_start:])
            nested_error = nested_payload.get("error")
            if isinstance(nested_error, dict):
                code = nested_error.get("code") or code
                message = str(nested_error.get("message") or message)
        except ValueError:
            pass

    return str(code) if code is not None else None, message[:2000]


def _video_payload_for_log(payload: dict) -> dict:
    sanitized = _payload_for_log(payload)
    prompt = sanitized.pop("prompt", None)
    if isinstance(prompt, str):
        sanitized["prompt_characters"] = len(prompt)
    return sanitized


async def get_models() -> list[dict]:
    """Return the complete OpenRouter catalog, including non-text models."""
    headers = {"Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{OPENROUTER_ENDPOINT}/models",
            params={"output_modalities": "all"},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", [])


async def get_video_models() -> list[dict]:
    headers = {"Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{OPENROUTER_ENDPOINT}/videos/models",
            headers=headers,
        )
        response.raise_for_status()
        return response.json().get("data", [])


async def get_image_models() -> list[dict]:
    headers = {"Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}"}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{OPENROUTER_ENDPOINT}/images/models",
            headers=headers,
        )
        response.raise_for_status()
        return response.json().get("data", [])


async def submit_video(payload: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{OPENROUTER_ENDPOINT}/videos",
            json=payload,
            headers=headers,
        )
        if response.status_code >= 400:
            provider_code, provider_message = _video_error_details(response)
            await openrouter_logger.error(
                "OpenRouter",
                f"VideoHTTPError_{response.status_code}",
                f"Provider code: {provider_code or 'unknown'}. "
                f"Response: {provider_message}. Payload: {_video_payload_for_log(payload)}",
            )
            raise OpenRouterVideoError(
                response.status_code,
                provider_message,
                provider_code,
            )
        response.raise_for_status()
        return response.json()


async def wait_for_video(
    job: dict,
    poll_interval: int = 30,
    max_attempts: int = 20,
) -> dict:
    headers = {"Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}"}
    current = job
    async with httpx.AsyncClient(timeout=120) as client:
        for _ in range(max_attempts):
            status = str(current.get("status", "")).lower()
            if status == "completed":
                return current
            if status in {"failed", "cancelled", "expired"}:
                raise RuntimeError(current.get("error") or f"Video job ended as {status}")

            await asyncio.sleep(poll_interval)
            polling_url = current.get("polling_url")
            if not polling_url:
                job_id = current.get("id")
                polling_url = f"{OPENROUTER_ENDPOINT}/videos/{job_id}"
            elif str(polling_url).startswith("/"):
                polling_url = f"https://openrouter.ai{polling_url}"

            response = await client.get(polling_url, headers=headers)
            response.raise_for_status()
            current = response.json()

    raise TimeoutError("Video generation did not finish within 10 minutes")


async def download_video(job_id: str) -> bytes:
    headers = {"Authorization": f"Bearer {get_env_var('OPENROUTER_KEY')}"}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.get(
            f"{OPENROUTER_ENDPOINT}/videos/{job_id}/content",
            params={"index": 0},
            headers=headers,
        )
        response.raise_for_status()
        return response.content


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
