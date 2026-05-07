from sqlalchemy import and_, select

from database.models.base import WhiteList
from database.operations import BaseRepository


class WhiteListRepository(BaseRepository[WhiteList]):
    def __init__(self, db):
        super().__init__(WhiteList, db)

    async def is_whitelisted(self, sender_type: str, sender_id: int) -> bool:
        result = await self.db.execute(
            select(WhiteList).filter(
                and_(
                    WhiteList.sender_type == sender_type,
                    WhiteList.sender_id == sender_id,
                    WhiteList.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def is_admin(self, sender_type: str, sender_id: int) -> bool:
        result = await self.db.execute(
            select(WhiteList).filter(
                and_(
                    WhiteList.sender_type == sender_type,
                    WhiteList.sender_id == sender_id,
                    WhiteList.is_admin == True,
                    WhiteList.deleted_at.is_(None)
                )
            )
        )
        return result.scalar_one_or_none() is not None

    async def add_to_whitelist(self, sender_type: str, sender_id: int, is_admin: bool = False) -> WhiteList:
        whitelist_entry = WhiteList(
            sender_type=sender_type,
            sender_id=sender_id,
            is_admin=is_admin
        )
        return await self.insert(whitelist_entry)

    async def remove_from_whitelist(self, sender_type: str, sender_id: int) -> bool:
        from datetime import datetime

        result = await self.db.execute(
            select(WhiteList).filter(
                and_(
                    WhiteList.sender_type == sender_type,
                    WhiteList.sender_id == sender_id,
                    WhiteList.deleted_at.is_(None)
                )
            )
        )
        entry = result.scalar_one_or_none()

        if not entry:
            return False

        return await self.update(entry.id, {"deleted_at": datetime.now()}) is not None
