from typing import Optional

from database.models.manager import Agent
from database.operations import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, db):
        super().__init__(Agent, db)

    async def find_by_name(self, name: str) -> Optional[Agent]:
        return await self.find_one_by(name=name)

    async def upsert_by_name(self, name: str, prompt: str, model_id: int) -> Agent:
        existing_agent = await self.find_by_name(name)

        if existing_agent:
            return await self.update(existing_agent.id, {"prompt": prompt, "model_id": model_id})
        else:
            new_agent = Agent(name=name, prompt=prompt, model_id=model_id)
            return await self.insert(new_agent)
