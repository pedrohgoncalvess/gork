from typing import Optional

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert

from database.models.manager import Agent
from database.operations import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, db):
        super().__init__(Agent, db)

    async def find_by_name(self, name: str) -> Optional[Agent]:
        return await self.find_one_by(name=name)

    async def upsert_by_name(self, name: str, prompt: str, model_id: int, response_format: str = None) -> Agent:
        # Multiple Gunicorn workers initialize new agents concurrently. Resolve
        # conflicts in PostgreSQL, preserving the latest admin-managed settings.
        statement = insert(Agent).values(
            name=name, prompt=prompt, model_id=model_id, response_format=response_format,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[Agent.name],
            set_={
                "prompt": case((Agent.prompt_managed, Agent.prompt), else_=statement.excluded.prompt),
                "model_id": case((Agent.model_managed, Agent.model_id), else_=statement.excluded.model_id),
                "response_format": statement.excluded.response_format,
            },
        ).returning(Agent).execution_options(populate_existing=True)
        result = await self.db.execute(statement)
        agent = result.scalar_one()
        await self.db.commit()
        return agent
