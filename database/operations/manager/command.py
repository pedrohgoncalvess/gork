from typing import List

from sqlalchemy import and_, desc, select

from database.models.manager import Command
from database.operations import BaseRepository


class CommandRepository(BaseRepository[Command]):
    async def find_by_user(self, user_id: int, limit: int = 50) -> List[Command]:
        result = await self.db.execute(
            select(Command)
            .filter(Command.user_id == user_id)
            .order_by(desc(Command.inserted_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_group(self, group_id: int, limit: int = 50) -> List[Command]:
        result = await self.db.execute(
            select(Command)
            .filter(Command.group_id == group_id)
            .order_by(desc(Command.inserted_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def find_by_user_and_group(
            self,
            user_id: int,
            group_id: int,
            limit: int = 50
    ) -> List[Command]:
        result = await self.db.execute(
            select(Command)
            .filter(
                and_(
                    Command.user_id == user_id,
                    Command.group_id == group_id
                )
            )
            .order_by(desc(Command.inserted_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_command(
            self,
            command: str,
            user_id: int,
            group_id: int = None
    ) -> Command:
        """Cria um novo comando"""
        new_command = Command(
            command=command,
            user_id=user_id,
            group_id=group_id
        )
        return await self.insert(new_command)
