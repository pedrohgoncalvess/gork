from typing import Optional, List
from sqlalchemy import select

from database.models.manager import Model
from database.operations import BaseRepository


class ModelRepository(BaseRepository[Model]):
    async def find_by_name(self, name: str) -> Optional[Model]:
        return await self.find_one_by(name=name)

    async def find_by_openrouter_id(self, openrouter_id: str) -> Optional[Model]:
        return await self.find_one_by(openrouter_id=openrouter_id)

    async def get_default_model(self) -> Optional[Model]:
        result = await self.db.execute(
            select(Model).filter(Model.text_default == True)
        )
        return result.scalar_one_or_none()

    async def get_default_audio_model(self) -> Optional[Model]:
        result = await self.db.execute(
            select(Model).filter(Model.audio_default == True)
        )
        return result.scalar_one_or_none()

    async def get_default_embedding_model(self) -> Optional[Model]:
        result = await self.db.execute(
            select(Model).filter(Model.embedding_default == True)
        )
        return result.scalar_one_or_none()

    async def get_default_image_model(self) -> Optional[Model]:
        result = await self.db.execute(
            select(Model).filter(Model.image_default == True)
        )
        return result.scalar_one_or_none()

    async def set_as_default(self, model_id: int) -> Optional[Model]:
        all_models = await self.find_all()
        for model in all_models:
            if model.text_default:
                await self.update(model.id, {"default": 0})

        return await self.update(model_id, {"default": 1})

    async def get_all_active(self) -> List[Model]:
        return await self.find_all()