import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from external.waha.base import request, segment, waha_api, waha_api_key, waha_session
from external.waha.identifiers import get_reference, message_payload, save_reference, sent_response


def file_payload(value: str, filename: str, mimetype: str) -> dict:
    file = {"filename": filename, "mimetype": mimetype}
    if value.startswith(("https://", "http://")):
        file["url"] = value
    else:
        if value.startswith("data:"):
            header, value = value.split(",", 1)
            file["mimetype"] = header[5:].split(";", 1)[0]
        file["data"] = value
    return file


async def send_file(contact_id: str, endpoint: str, value: str, filename: str,
                    mimetype: str, quoted: str | None = None, **options) -> dict:
    payload = await message_payload(contact_id, quoted)
    payload.update(file=file_payload(value, filename, mimetype), **options)
    response = await request("POST", endpoint, payload=payload)
    return await sent_response(response, contact_id)


async def _download_file(media: dict) -> tuple[str, str]:
    url = media.get("url")
    if not url:
        raise ValueError("WAHA did not provide a downloadable media URL")
    parsed = urlsplit(url)
    # WAHA can advertise localhost/public URLs. Fetch its file path through the
    # configured internal service, never forward API credentials to another host.
    if not parsed.path.startswith(("/api/files/", "/files/")):
        raise ValueError("Unexpected WAHA media path")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(waha_api + parsed.path, headers={"X-Api-Key": waha_api_key})
        response.raise_for_status()
    name = media.get("filename") or media.get("fileName") or Path(parsed.path).name
    return base64.b64encode(response.content).decode(), name


async def download_media(message_id: str) -> tuple[str, str]:
    reference = await get_reference(message_id)
    if not reference:
        # Old media remains in S3. Only unarchived WAHA media needs a provider ref.
        raise ValueError(f"No WAHA media reference for message {message_id}")
    if (reference.get("media") or {}).get("url"):
        try:
            return await _download_file(reference["media"])
        except httpx.HTTPStatusError as error:
            if error.response.status_code not in (404, 410):
                raise
    path = (f"/api/{segment(waha_session)}/chats/{segment(reference['chat_id'])}"
            f"/messages/{segment(reference['provider_id'])}")
    payload = await request("GET", path, params={"downloadMedia": "true"})
    await save_reference(payload, reference["chat_id"])
    return await _download_file(payload.get("media") or {})


async def send_media(contact_id: str, file_path: str):
    path = Path(file_path)
    value = base64.b64encode(path.read_bytes()).decode()
    return await send_file(contact_id, "/api/sendFile", value, path.name,
                           mimetypes.guess_type(path.name)[0] or "application/octet-stream")
