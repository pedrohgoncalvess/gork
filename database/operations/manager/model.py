from typing import List, Optional

from sqlalchemy import desc, select

from database.models.manager import Model, ModelPrice
from database.operations import BaseRepository


class ModelRepository(BaseRepository[Model]):
    def __init__(self, db):
        super().__init__(Model, db)

    async def find_by_name(self, name: str) -> Optional[Model]:
        return await self.find_one_by(name=name)

    async def find_by_openrouter_id(self, openrouter_id: str) -> Optional[Model]:
        return await self.find_one_by(openrouter_id=openrouter_id)

    async def get_default_embedding_model(self) -> Optional[Model]:
        result = await self.db.execute(
            select(Model).filter(Model.embedding_default == True)
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> List[Model]:
        return await self.find_all()

    async def get_latest_price(self, model_id: int) -> Optional[ModelPrice]:
        result = await self.db.execute(
            select(ModelPrice)
            .filter(ModelPrice.model_id == model_id)
            .order_by(desc(ModelPrice.fetched_at), desc(ModelPrice.id))
            .limit(1)
        )
        return result.scalar_one_or_none()
