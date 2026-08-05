from typing import Optional
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models.content.sup_media import SupMedia
from database.operations import BaseRepository


class SupMediaRepository(BaseRepository[SupMedia]):
    def __init__(self, db):
        super().__init__(SupMedia, db)

    async def find_by_name(self, name: str) -> Optional[SupMedia]:
        return await self.find_one_by(name=name)

    async def upsert_by_name(self, name: str, bucket: str, path: str, media_type: str) -> SupMedia:
        stmt = (
            pg_insert(SupMedia)
            .values(
                name=name,
                bucket=bucket,
                path=path,
                type=media_type,
            )
            .on_conflict_do_update(
                index_elements=["name"],
                set_={
                    "bucket": bucket,
                    "path": path,
                    "type": media_type,
                }
            )
            .returning(SupMedia)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        return result.scalar_one()
