from fastapi import FastAPI

from api import webhook_evolution_router
from database import init_agents
from scheduler import scheduler
from services import set_remembers


app = FastAPI()
app.include_router(webhook_evolution_router)

@app.on_event("startup")
async def startup_event():
    await init_agents()
    await set_remembers(scheduler)
    scheduler.start()
