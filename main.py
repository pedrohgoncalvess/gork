from fastapi import FastAPI

from api import webhook_evolution_router
from agents.init import init_agents
from assets.init import init_assets
from database import dispose_database_engine
from scheduler import scheduler
from services import set_remembers


app = FastAPI()
app.include_router(webhook_evolution_router)

@app.on_event("startup")
async def startup_event():
    await init_agents()
    await init_assets()
    await set_remembers(scheduler)
    scheduler.start()


@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)
    await dispose_database_engine()
