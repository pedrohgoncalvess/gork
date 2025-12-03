# database/repositories/remember_repository.py
from typing import Optional, List
from datetime import datetime
from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased

from database.models.base import User, Group
from database.models.manager import Remember
from database.operations import BaseRepository


class RememberRepository(BaseRepository[Remember]):

    async def find_by_user(self, user_id: int) -> List[Remember]:
        return await self.find_all_by(user_id=user_id, deleted_at=None)

    async def find_by_group(self, group_id: int) -> List[Remember]:
        return await self.find_all_by(group_id=group_id, deleted_at=None)

    async def find_pending(self, limit_datetime: datetime = None) -> List[tuple[Remember, str | None, str | None]]:
        if limit_datetime is None:
            limit_datetime = datetime.now()

        U = aliased(User)
        G = aliased(Group)

        query = (
            self.session.query(Remember, U.phone_number.label("user_src_id"), G.src_id.label("group_src_id"))
            .outerjoin(U, Remember.user_id == U.id)
            .outerjoin(G, Remember.group_id == G.id)
            .filter(
                and_(
                    Remember.deleted_at.is_(None),
                    Remember.remember_at <= limit_datetime
                )
            )
            .order_by(Remember.remember_at)
        )

        result = await self.session.execute(query)
        rows = result.all()

        return rows

    async def find_upcoming(
            self,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None,
            limit: int = 10
    ) -> List[Remember]:
        """
        Busca próximos lembretes (futuros e não deletados)

        Args:
            user_id: Filtrar por usuário específico
            group_id: Filtrar por grupo específico
            limit: Quantidade máxima de resultados
        """
        filters = [
            Remember.deleted_at.is_(None),
            Remember.remember_at > datetime.now()
        ]

        if user_id:
            filters.append(Remember.user_id == user_id)

        if group_id:
            filters.append(Remember.group_id == group_id)

        query = (
            self.session.query(Remember)
            .filter(and_(*filters))
            .order_by(Remember.remember_at)
            .limit(limit)
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def create_remember(
            self,
            remember_at: datetime,
            message: str,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None
    ) -> Remember:
        remember = Remember(
            user_id=user_id,
            group_id=group_id,
            remember_at=remember_at,
            message=message
        )
        return await self.insert(remember)

    async def soft_delete(self, remember_id: int) -> Optional[Remember]:
        """
        Marca um lembrete como deletado (soft delete)

        Args:
            remember_id: ID do lembrete
        """
        return await self.update(
            remember_id,
            {"deleted_at": datetime.now()}
        )

    async def find_by_user_or_group(
            self,
            user_id: Optional[int] = None,
            group_id: Optional[int] = None
    ) -> List[Remember]:
        """
        Busca lembretes por usuário OU grupo

        Args:
            user_id: ID do usuário
            group_id: ID do grupo
        """
        filters = [Remember.deleted_at.is_(None)]

        if user_id and group_id:
            filters.append(
                or_(
                    Remember.user_id == user_id,
                    Remember.group_id == group_id
                )
            )
        elif user_id:
            filters.append(Remember.user_id == user_id)
        elif group_id:
            filters.append(Remember.group_id == group_id)
        else:
            return []

        query = (
            self.session.query(Remember)
            .filter(and_(*filters))
            .order_by(Remember.remember_at)
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def count_pending_by_user(self, user_id: int) -> int:
        """Conta quantos lembretes pendentes um usuário tem"""
        query = (
            self.session.query(Remember)
            .filter(
                and_(
                    Remember.user_id == user_id,
                    Remember.deleted_at.is_(None),
                    Remember.remember_at > datetime.now()
                )
            )
        )

        result = await self.session.execute(query)
        return len(result.scalars().all())