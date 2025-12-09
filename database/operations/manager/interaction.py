from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, and_, desc, func as sql_func
from sqlalchemy.orm import joinedload

from database.models.manager import Interaction
from database.operations import BaseRepository
from database.models.base import User
from database.models.manager import Model


class InteractionRepository(BaseRepository[Interaction]):

    async def get_consumption_by_user(
            self,
            group_id: Optional[int] = None,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None,
            user_id: Optional[int] = None,
            model_id: Optional[int] = None,
            agent_id: Optional[int] = None,
            command_id: Optional[int] = None
    ) -> List[dict]:

        if start_date is None:
            start_date = datetime.now() - timedelta(days=1)

        filters = []
        filters.append(Interaction.inserted_at >= start_date)

        if user_id:
            filters.append(Interaction.user_id <= user_id)

        if end_date:
            filters.append(Interaction.inserted_at <= end_date)

        if group_id is not None:
            filters.append(Interaction.group_id == group_id)

        if model_id:
            filters.append(Interaction.model_id == model_id)
        if agent_id:
            filters.append(Interaction.agent_id == agent_id)
        if command_id:
            filters.append(Interaction.command_id == command_id)

        result = await self.db.execute(
            select(
                Interaction.user_id,
                User.name.label('user_name'),
                Interaction.model_id,
                Model.name.label('model_name'),
                Model.input_price,
                Model.output_price,
                sql_func.count(Interaction.id).label('interaction_count'),
                sql_func.sum(Interaction.input_tokens).label('total_input_tokens'),
                sql_func.sum(Interaction.output_tokens).label('total_output_tokens')
            )
            .join(User, Interaction.user_id == User.id)
            .join(Model, Interaction.model_id == Model.id)
            .filter(and_(*filters))
            .group_by(
                Interaction.user_id,
                User.name,
                Interaction.model_id,
                Model.name,
                Model.input_price,
                Model.output_price
            )
            .order_by(User.name, Model.name)
        )

        rows = result.all()

        user_data = {}
        for row in rows:
            user_id = row.user_id

            if user_id not in user_data:
                user_data[user_id] = {
                    'user_id': user_id,
                    'user_name': row.user_name,
                    'total_interactions': 0,
                    'total_input_tokens': 0,
                    'total_output_tokens': 0,
                    'total_tokens': 0,
                    'estimated_cost': 0.0,
                    'models_used': []
                }

            input_tokens = row.total_input_tokens or 0
            output_tokens = row.total_output_tokens or 0
            total_tokens = input_tokens + output_tokens

            input_price = float(row.input_price or 0)
            output_price = float(row.output_price or 0)

            model_cost = (
                    (input_tokens * input_price / 1_000_000) +
                    (output_tokens * output_price / 1_000_000)
            )

            user_data[user_id]['models_used'].append({
                'model_id': row.model_id,
                'model_name': row.model_name,
                'interaction_count': row.interaction_count,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': total_tokens,
                'input_price_per_1m': input_price,
                'output_price_per_1m': output_price,
                'estimated_cost': round(model_cost, 6)
            })

            user_data[user_id]['total_interactions'] += row.interaction_count
            user_data[user_id]['total_input_tokens'] += input_tokens
            user_data[user_id]['total_output_tokens'] += output_tokens
            user_data[user_id]['total_tokens'] += total_tokens
            user_data[user_id]['estimated_cost'] += model_cost

        result_list = []
        for user in user_data.values():
            user['estimated_cost'] = round(user['estimated_cost'], 6)
            result_list.append(user)

        result_list.sort(key=lambda x: x['estimated_cost'], reverse=True)

        return result_list

    async def find_by_user(self, user_id: int, limit: int = 100) -> List[Interaction]:
        result = await self.db.execute(
            select(Interaction)
            .filter(Interaction.user_id == user_id)
            .order_by(desc(Interaction.inserted_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_interaction(
            self,
            model_id: int,
            user_id: int,
            group_id: Optional[int],
            user_prompt: str,
            response: str,
            input_tokens: int,
            output_tokens: int,
            command_id: Optional[int] = None,
            agent_id: Optional[int] = None,
            system_behavior: Optional[str] = None
    ,
    ) -> Interaction:
        interaction = Interaction(
            model_id=model_id,
            user_id=user_id,
            user_prompt=user_prompt,
            group_id=group_id,
            system_behavior=system_behavior,
            response=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            command_id=command_id,
            agent_id=agent_id,
        )
        return await self.insert(interaction)

    async def get_total_tokens_by_user(
            self,
            user_id: int,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> int:
        filters = [Interaction.user_id == user_id]

        if start_date:
            filters.append(Interaction.inserted_at >= start_date)
        if end_date:
            filters.append(Interaction.inserted_at <= end_date)

        result = await self.db.execute(
            select(sql_func.sum(Interaction.tokens))
            .filter(and_(*filters))
        )
        total = result.scalar_one_or_none()
        return total if total else 0

    async def get_interactions_count(
            self,
            model_id: Optional[int] = None,
            agent_id: Optional[int] = None,
            user_id: Optional[int] = None,
            hours: Optional[int] = None
    ) -> int:
        filters = []

        if model_id:
            filters.append(Interaction.model_id == model_id)
        if agent_id:
            filters.append(Interaction.agent_id == agent_id)
        if user_id:
            filters.append(Interaction.user_id == user_id)
        if hours:
            time_threshold = datetime.now() - timedelta(hours=hours)
            filters.append(Interaction.inserted_at >= time_threshold)

        result = await self.db.execute(
            select(sql_func.count(Interaction.id))
            .filter(and_(*filters) if filters else True)
        )
        return result.scalar_one()

    async def get_recent_interactions(
            self,
            hours: int = 24,
            limit: int = 50,
            include_agent: bool = False,
            include_user: bool = False
    ) -> List[Interaction]:
        time_threshold = datetime.now() - timedelta(hours=hours)

        options = [
            joinedload(Interaction.model),
            joinedload(Interaction.command)
        ]
        if include_agent:
            options.append(joinedload(Interaction.agent))
        if include_user:
            options.append(joinedload(Interaction.user))

        result = await self.db.execute(
            select(Interaction)
            .options(*options)
            .filter(Interaction.inserted_at >= time_threshold)
            .order_by(desc(Interaction.inserted_at))
            .limit(limit)
        )
        return list(result.unique().scalars().all())

    async def get_child_interactions(self, parent_interaction_id: int) -> List[Interaction]:
        result = await self.db.execute(
            select(Interaction)
            .filter(Interaction.interaction_id == parent_interaction_id)
            .order_by(Interaction.inserted_at)
        )
        return list(result.scalars().all())

    async def calculate_cost(
            self,
            command_id: Optional[int] = None,
            model_id: Optional[int] = None,
            agent_id: Optional[int] = None,
            user_id: Optional[int] = None,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> dict:
        filters = []
        if command_id:
            filters.append(Interaction.command_id == command_id)
        if model_id:
            filters.append(Interaction.model_id == model_id)
        if agent_id:
            filters.append(Interaction.agent_id == agent_id)
        if user_id:
            filters.append(Interaction.user_id == user_id)
        if start_date:
            filters.append(Interaction.inserted_at >= start_date)
        if end_date:
            filters.append(Interaction.inserted_at <= end_date)

        result = await self.db.execute(
            select(
                sql_func.sum(Interaction.tokens).label('total_tokens'),
                sql_func.count(Interaction.id).label('interaction_count')
            )
            .filter(and_(*filters) if filters else True)
        )

        row = result.one_or_none()

        return {
            "total_tokens": row.total_tokens if row and row.total_tokens else 0,
            "interaction_count": row.interaction_count if row else 0
        }

    async def get_user_stats(
            self,
            user_id: int,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None
    ) -> dict:
        filters = [Interaction.user_id == user_id]

        if start_date:
            filters.append(Interaction.inserted_at >= start_date)
        if end_date:
            filters.append(Interaction.inserted_at <= end_date)

        result = await self.db.execute(
            select(
                sql_func.count(Interaction.id).label('total_interactions'),
                sql_func.sum(Interaction.tokens).label('total_tokens'),
                sql_func.count(sql_func.distinct(Interaction.command_id)).label('unique_commands'),
                sql_func.count(sql_func.distinct(Interaction.model_id)).label('unique_models')
            )
            .filter(and_(*filters))
        )

        row = result.one_or_none()

        return {
            "total_interactions": row.total_interactions if row else 0,
            "total_tokens": row.total_tokens if row and row.total_tokens else 0,
            "unique_commands": row.unique_commands if row else 0,
            "unique_models": row.unique_models if row else 0
        }