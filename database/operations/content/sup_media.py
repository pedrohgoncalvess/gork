from typing import Optional

from database.models.content.sup_media import SupMedia
from database.operations import BaseRepository


class SupMediaRepository(BaseRepository[SupMedia]):
    def __init__(self, db):
        super().__init__(SupMedia, db)

    async def find_by_name(self, name: str) -> Optional[SupMedia]:
        return await self.find_one_by(name=name)

    async def upsert_by_name(self, name: str, bucket: str, path: str, media_type: str) -> SupMedia:
        existing = await self.find_by_name(name)
        if existing:
            return await self.update(existing.id, {
                "bucket": bucket,
                "path": path,
                "type": media_type,
            })

        new_record = SupMedia(
            name=name,
            bucket=bucket,
            path=path,
            type=media_type,
        )
        return await self.insert(new_record)
