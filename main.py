import asyncio

from fastapi import FastAPI

from api import webhook_evolution_router
from agents.init import init_agents
from assets.init import init_assets
from database import dispose_database_engine
from database.migrate import apply_pending_migrations
from log import logger
from scheduler import scheduler
from services import set_model_price_refresh, set_remembers


app = FastAPI()
app.include_router(webhook_evolution_router)

@app.on_event("startup")
async def startup_event():
    applied_migrations = await asyncio.to_thread(apply_pending_migrations)
    await logger.info(
        "Database",
        "Migrations",
        f"Applied {applied_migrations} pending migration(s).",
    )
    await set_model_price_refresh(scheduler)
    await init_agents()
    await init_assets()
    await set_remembers(scheduler)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)
    await dispose_database_engine()
