import json
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import PgConnection
from database.models.manager import Command, Remember
from database.operations.manager import CommandRepository
from database.operations.manager.remember import RememberRepository
from external.evolution import send_message
from services import manage_interaction, action_remember


async def remember_generator(user_id: int, message: str, group_id: int = None) -> tuple[Remember, str]:

    async with PgConnection() as db:
        command_repo = CommandRepository(Command, db)
        remember_repo = RememberRepository(Remember, db)

        new_command = await command_repo.insert(Command(
            user_id=user_id,
            command="remember",
            group_id=group_id,
        ))
        resp = await manage_interaction(db, message, agent_name="remember-formatter", command=new_command, user_id=user_id, group_id=group_id)
        formatted_resp = json.loads(f"""{resp}""")
        time_remember = datetime.strptime(formatted_resp.get("datetime"), "%Y-%m-%d %H:%M:%S")
        message = formatted_resp.get("message")

        remember = await remember_repo.create_remember(
            user_id=user_id,
            group_id=group_id,
            remember_at=time_remember,
            message=message,
        )

        return remember, formatted_resp.get("feedback_message")


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
