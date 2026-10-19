import asyncio
import secrets
import traceback

from fastapi import APIRouter, HTTPException, Request

from api.routes.webhook.waha.services import process_waha_webhook
from api.routes.webhook.waha.normalize import normalize_webhook
from log import logger
from scheduler import scheduler
from utils import get_env_var


router = APIRouter(prefix="/webhook/waha", tags=["Webhook", "WAHA", "WhatsApp Events"])
background_tasks = set()


def _handle_webhook_task_exception(task: asyncio.Task) -> None:
    background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log_task = asyncio.create_task(logger.error("Webhook", "TaskError", f"{task.get_name()}: {exc}\n{tb}"))
        background_tasks.add(log_task)
        log_task.add_done_callback(background_tasks.discard)


@router.post("")
async def waha_webhook(request: Request):
    token = get_env_var("WAHA_WEBHOOK_TOKEN")
    supplied = request.headers.get("X-Webhook-Token", "")
    if not token or not secrets.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object")
    if body.get("session") != (get_env_var("WAHA_SESSION") or "default"):
        raise HTTPException(status_code=403, detail="Unexpected WAHA session")
    if body.get("event") not in ("message.any", "message"):
        return {"status": "ignored"}
    if not isinstance(body.get("payload"), dict):
        raise HTTPException(status_code=400, detail="Invalid message payload")
    try:
        normalized = normalize_webhook(body)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid message payload")
    if normalized is None:
        return {"status": "ignored"}
    task = asyncio.create_task(process_waha_webhook(body, scheduler), name=f"waha:{body.get('id')}")
    background_tasks.add(task)
    task.add_done_callback(_handle_webhook_task_exception)
    return {"status": "received"}
