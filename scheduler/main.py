from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler


scheduler = AsyncIOScheduler(timezone=ZoneInfo("America/Sao_Paulo"))