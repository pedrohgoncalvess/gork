from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from external.evolution import send_message
from services import action_remember
from api.routes.webhook.evolution.functions import remember_generator


async def handle_remember_command(
        scheduler: AsyncIOScheduler,
        remote_id: str,
        message_id: str,
        user_id: int,
        treated_text: str,
        group_id: Optional[int] = None
):
    remember, feedback_message = await remember_generator(user_id, treated_text, group_id)
    remember.message = f"*[LEMBRETE]* {remember.message}"
    remember.remember_at = remember.remember_at.replace(tzinfo=ZoneInfo("America/Sao_Paulo"))

    scheduler.add_job(
        action_remember,
        'date',
        run_date=remember.remember_at,
        args=[remember, remote_id],
        id=str(remember.id)
    )
    await send_message(remote_id, feedback_message, message_id)
