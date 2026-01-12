from apscheduler.schedulers.asyncio import AsyncIOScheduler

from api.routes.webhook.evolution.processors import process_group_message, process_private_message
from database import PgConnection
from external.evolution import send_message
from log import logger
from utils import get_env_var


maintenance = get_env_var("MAINTENANCE")
maintenance_number = get_env_var("MAINTENANCE_NUMBER")

async def process_webhook(body: dict, scheduler: AsyncIOScheduler):
    async with PgConnection() as db:
        event_type = body.get("event")
        event_data = body.get("data")

        if event_type != "messages.upsert":
            return

        await logger.info("Request", body.get("instance"), body)

        remote_id = event_data.get("key", {}).get("remoteJid", "")
        alt_id = event_data.get("key", {}).get("remoteJidAlt", "")

        if remote_id.endswith(".net"):
            is_private = True
            phone_number = remote_id.replace("@s.whatsapp.net", "")
            remote_id = alt_id.replace("@lid", "")
        elif alt_id.endswith(".net"):
            is_private = True
            phone_number = alt_id.replace("@s.whatsapp.net", "")
            remote_id = remote_id.replace("@lid", "")
        elif remote_id.endswith("@g.us"):
            is_private = False

        if maintenance:
            if is_private:
                if phone_number != maintenance_number:
                    await send_message(phone_number, "O robo do mito não está pronto :/")
                    return
            else:
                return

        if not is_private:
            await process_group_message(
                body, remote_id, db, scheduler
            )
        elif is_private:
            await process_private_message(
                body, event_data, remote_id, phone_number, db, scheduler
            )