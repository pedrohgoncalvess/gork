import uvicorn
from scheduler import scheduler
from fastapi import FastAPI

from database import init_agents
from services import set_remembers
from api import webhook_evolution_router


app = FastAPI()
app.include_router(webhook_evolution_router)

@app.on_event("startup")
async def startup_event():
    await init_agents()
    await set_remembers(scheduler)
    scheduler.start()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=90001)
