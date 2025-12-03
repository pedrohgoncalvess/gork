import json
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import PgConnection
from database.models.manager import Command, Remember
from database.operations.manager import CommandRepository
from database.operations.manager.remember import RememberRepository
from external.evolution import send_message
from services import manage_interaction


async def remember_generator(user_id: int, message: str, group_id: int = None) -> tuple[Remember, str]:

    async with PgConnection() as db:
        command_repo = CommandRepository(Command, db)
        remember_repo = RememberRepository(Remember, db)

        new_command = await command_repo.insert(Command(
            user_id=user_id,
            command="!remember",
            group_id=group_id,
        ))
        resp = await manage_interaction(db, message, agent_name="remember-formatter", command=new_command)
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