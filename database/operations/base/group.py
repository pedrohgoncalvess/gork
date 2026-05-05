from typing import Optional, List

from database.models.base import Group
from database.operations import BaseRepository


class GroupRepository(BaseRepository[Group]):
    def __init__(self, db):
        super().__init__(Group, db)

    async def find_by_src_id(self, group_jid: str) -> Optional[Group]:
        return await self.find_one_by(src_id=group_jid)

    async def find_by_name(self, name: str) -> List[Group]:
        return await self.find_by(name=name)

    async def find_or_create(self, group_jid: str, name: str = None, profile_image_url: str = None, description: str = None) -> Group:
        group = await self.find_by_src_id(group_jid)

        if group:
            update_data = {}
            if name:
                update_data["name"] = name
            if profile_image_url:
                update_data["profile_image_url"] = profile_image_url

            if update_data:
                return await self.update(group.id, update_data)
            return group

        new_group = Group(
            src_id=group_jid,
            description=description,
            name=name,
            profile_image_url=profile_image_url
        )
        return await self.insert(new_group)

    async def update_profile_image(self, group_jid: str, profile_image_url: str) -> Optional[Group]:
        group = await self.find_by_src_id(group_jid)
        if not group:
            return None
        return await self.update(group.id, {"profile_image_url": profile_image_url})