"""Configure/start Gork's WAHA session or fetch its status/QR code.

Run from the repository root: python -m scripts.waha_session configure
"""
import argparse
import asyncio
from pathlib import Path

import httpx

from external.waha.base import request, segment, waha_api, waha_api_key, waha_session
from utils import get_env_var


DEFAULT_WEBHOOK_URL = "http://api:9001/webhook/waha"
LEGACY_WEBHOOK_URL = "http://webhook_fastapi:9001/webhook/waha"


def get_webhook_url():
    value = get_env_var("WAHA_WEBHOOK_URL") or DEFAULT_WEBHOOK_URL
    return DEFAULT_WEBHOOK_URL if value == LEGACY_WEBHOOK_URL else value


def session_config(webhook_url: str, token: str) -> dict:
    if not token:
        raise ValueError("WAHA_WEBHOOK_TOKEN is required")
    webhook_url = DEFAULT_WEBHOOK_URL if webhook_url == LEGACY_WEBHOOK_URL else webhook_url
    return {
        "gows": {"storage": {"messages": True, "groups": True, "chats": True, "contacts": True, "messageSecrets": True}},
        "webhooks": [{
            "url": webhook_url, "events": ["message.any", "poll.vote", "poll.vote.failed"],
            "customHeaders": [{"name": "X-Webhook-Token", "value": token}],
            "retries": {"policy": "constant", "delaySeconds": 2, "attempts": 5},
        }],
    }


async def configure_session(webhook_url: str) -> str:
    path = f"/api/sessions/{segment(waha_session)}"
    try:
        current = await request("GET", path)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise
        current = await request("POST", "/api/sessions", payload={"name": waha_session, "start": False})
    # Preserve unrelated session options while updating the integration contract.
    config = {**(current.get("config") or {}), **session_config(webhook_url, get_env_var("WAHA_WEBHOOK_TOKEN"))}
    if config != (current.get("config") or {}):
        await request("PUT", path, payload={"name": waha_session, "config": config})
        current = await request("GET", path)
    status = current.get("status")
    if status in ("STOPPED", "FAILED"):
        action = "start" if status == "STOPPED" else "restart"
        current = await request("POST", f"{path}/{action}", payload={})
    return current.get("status", "STARTING")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "status", "qr"))
    parser.add_argument("--webhook-url", default=get_webhook_url())
    parser.add_argument("--output", default="waha-qr.png")
    args = parser.parse_args()
    if args.action == "configure":
        print(f"WAHA session {waha_session}: {await configure_session(args.webhook_url)}")
    elif args.action == "status":
        result = await request("GET", f"/api/sessions/{segment(waha_session)}")
        # Do not print config: it contains the webhook token.
        print({"name": result.get("name"), "status": result.get("status"), "me": result.get("me")})
    else:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{waha_api}/api/{segment(waha_session)}/auth/qr",
                                        headers={"X-Api-Key": waha_api_key, "Accept": "image/png"})
            response.raise_for_status()
        Path(args.output).write_bytes(response.content)
        print(f"QR saved to {Path(args.output).resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
