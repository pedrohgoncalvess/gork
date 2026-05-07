from typing import Optional

from sqlalchemy import and_, desc, select

from database.models.manager import Agent, Model, ModelConversation
from database.operations import BaseRepository


class ModelConversationRepository(BaseRepository[ModelConversation]):
    def __init__(self, db):
        super().__init__(ModelConversation, db)

    async def find_model_for_agent(
            self,
            agent_id: int,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None,
    ) -> Optional[Model]:
        filters = [ModelConversation.agent_id == agent_id]

        if group_id is not None:
            filters.append(ModelConversation.group_id == group_id)
        elif user_id is not None:
            filters.append(ModelConversation.user_id == user_id)
            filters.append(ModelConversation.group_id.is_(None))
        else:
            return None

        result = await self.db.execute(
            select(Model)
            .join(ModelConversation, ModelConversation.model_id == Model.id)
            .filter(and_(*filters))
            .order_by(desc(ModelConversation.inserted_at), desc(ModelConversation.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_override(
            self,
            agent_id: int,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None,
    ) -> Optional[ModelConversation]:
        filters = [ModelConversation.agent_id == agent_id]

        if group_id is not None:
            filters.append(ModelConversation.group_id == group_id)
        elif user_id is not None:
            filters.append(ModelConversation.user_id == user_id)
            filters.append(ModelConversation.group_id.is_(None))
        else:
            return None

        result = await self.db.execute(
            select(ModelConversation)
            .filter(and_(*filters))
            .order_by(desc(ModelConversation.inserted_at), desc(ModelConversation.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert_for_group(
            self,
            group_id: int,
            agent_id: int,
            model_id: int,
    ) -> ModelConversation:
        existing = await self.find_override(agent_id=agent_id, group_id=group_id)
        if existing:
            return await self.update(existing.id, {"model_id": model_id})

        return await self.insert(
            ModelConversation(
                group_id=group_id,
                agent_id=agent_id,
                model_id=model_id,
            )
        )

    async def upsert_for_user(
            self,
            user_id: int,
            agent_id: int,
            model_id: int,
    ) -> ModelConversation:
        existing = await self.find_override(agent_id=agent_id, user_id=user_id)
        if existing:
            return await self.update(existing.id, {"model_id": model_id})

        return await self.insert(
            ModelConversation(
                user_id=user_id,
                agent_id=agent_id,
                model_id=model_id,
            )
        )

    async def resolve_agent_model(
            self,
            agent: Agent,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None,
    ) -> Optional[Model]:
        conversation_model = await self.find_model_for_agent(
            agent_id=agent.id,
            user_id=user_id,
            group_id=group_id,
        )
        if conversation_model:
            return conversation_model

        result = await self.db.execute(
            select(Model).filter(Model.id == agent.model_id)
        )
        return result.scalar_one_or_none()
