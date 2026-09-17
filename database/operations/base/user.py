from typing import List, Optional

from sqlalchemy import and_, or_, select, desc

from database.models.base import User, Group
from database.operations import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, db):
        super().__init__(User, db)

    async def find_by_phone(self, phone_number: str) -> Optional[User]:
        from database.models.base.white_list import WhiteList

        result = await self.db.execute(
            select(self.model)
            .outerjoin(
                WhiteList,
                and_(
                    WhiteList.sender_type == "user",
                    WhiteList.sender_id == self.model.id,
                    WhiteList.deleted_at.is_(None),
                ),
            )
            .filter(self.model.phone_number == phone_number)
            .order_by(WhiteList.id.is_(None), self.model.id.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_phone_or_id(self, _id: str) -> Optional[User]:
        query = select(self.model).filter(
            or_(
                self.model.phone_number == _id,
                self.model.src_id == _id
            )
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def find_by_lid(self, lid: str) -> Optional[User]:
        return await self.find_one_by(src_id=lid)

    async def find_by_name(self, name: str) -> Optional[User]:
        return await self.find_one_by(name=name)

    async def find_or_create(
            self,
            lid: str,
            phone_number: str = None,
            name: str = None
    ) -> User:
        # A phone-only DM may already have produced a duplicate whose src_id is
        # also the phone number. Prefer the whitelisted phone match in that
        # payload shape so conversation ownership and access are preserved.
        if phone_number and lid == phone_number:
            user = await self.find_by_phone(phone_number)
        else:
            user = await self.find_by_lid(lid)

        if not user and phone_number:
            # Evolution sometimes sends the phone JID in both remoteJid and
            # remoteJidAlt for direct messages. In that case ``lid`` is the
            # phone number, so looking up only by src_id would create a second
            # user without the original user's whitelist entry.
            user = await self.find_by_phone(phone_number)

        if user:
            update_data = {}
            if name and user.name is not None:
                update_data["name"] = name
            if phone_number and user.phone_number != phone_number:
                update_data["phone_number"] = phone_number
            if lid != phone_number and user.src_id != lid:
                update_data["src_id"] = lid

            if update_data:
                return await self.update(user.id, update_data)
            return user

        new_user = User(
            src_id=lid,
            phone_number=phone_number,
            name=name
        )
        return await self.insert(new_user)

    async def find_users_by_group_id(self, group_id: int) -> List[User]:
        from database.models.content import Message
        query = (
            select(self.model)
            .join(Message, Message.user_id == self.model.id)
            .where(Message.group_id == group_id)
            .distinct()
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())
