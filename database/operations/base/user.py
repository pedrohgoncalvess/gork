from typing import Optional

from sqlalchemy import select, or_

from database.models.base import User
from database.operations import BaseRepository


class UserRepository(BaseRepository[User]):
    async def find_by_phone(self, phone_number: str) -> Optional[User]:
        return await self.find_one_by(phone_number=phone_number)

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
        user = await self.find_by_lid(lid)
        if user:
            update_data = {}
            if name and user.name is not None:
                update_data["name"] = name
            if phone_number and user.phone_number != phone_number:
                update_data["phone_number"] = phone_number

            if update_data:
                return await self.update(user.id, update_data)
            return user

        new_user = User(
            src_id=lid,
            phone_number=phone_number,
            name=name
        )
        return await self.insert(new_user)