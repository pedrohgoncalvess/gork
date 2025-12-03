from apscheduler.schedulers.asyncio import AsyncIOScheduler

from database import PgConnection
from database.models.manager import Remember
from database.operations.manager import RememberRepository
from external.evolution import send_message


async def set_remembers(scheduler: AsyncIOScheduler):
    async with PgConnection() as db:
        remeber_repo = RememberRepository(Remember, db)
        remembers = await remeber_repo.find_pending()
        for remember, usr_id, gp_id in remembers:
            remote_id = f"{gp_id}@g.us" if gp_id else usr_id
            remember.message = f"*[LEMBRETE]* {remember.message}"
            scheduler.add_job(
                action_remember,
                'date',
                run_date=remember.remember_at,
                args=[remember, remote_id],
                id=str(remember.id)
            )
            return

async def action_remember(remember: Remember, remote_id: str):
    async with PgConnection() as db:
        remember_repo = RememberRepository(Remember, db)
        await send_message(remote_id, remember.message)
        _ = await remember_repo.soft_delete(remember.id)
    return