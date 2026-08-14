from datetime import datetime

from sqlalchemy import and_, select

from database.models.base import BlackList
from database.operations import BaseRepository


class BlackListRepository(BaseRepository[BlackList]):
    def __init__(self, db):
        super().__init__(BlackList, db)

    async def get_active(self, user_id: int) -> BlackList | None:
        result = await self.db.execute(
            select(BlackList).where(
                and_(
                    BlackList.user_id == user_id,
                    BlackList.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def is_blacklisted(self, user_id: int) -> bool:
        return await self.get_active(user_id) is not None

    async def blocks_feature(self, user_id: int, feature: str) -> bool:
        entry = await self.get_active(user_id)
        if not entry:
            return False

        features = {
            self.normalize_feature(item)
            for item in (entry.features or [])
            if self.normalize_feature(item)
        }
        return not features or self.normalize_feature(feature) in features

    @staticmethod
    def normalize_feature(feature: str | None) -> str:
        normalized = str(feature or "").strip().lower().removeprefix("!")
        aliases = {
            "consumption": "usage",
            "message": "interaction",
            "send_audio": "audio",
            "send_image": "image",
            "send_video": "video",
            "web_search": "search",
        }
        return aliases.get(normalized, normalized)

    async def add(
        self,
        user_id: int,
        features: list[str] | None = None,
    ) -> BlackList:
        existing = await self.get_active(user_id)
        if existing:
            return existing
        normalized_features = sorted({
            self.normalize_feature(feature)
            for feature in (features or [])
            if self.normalize_feature(feature)
        })
        return await self.insert(
            BlackList(user_id=user_id, features=normalized_features)
        )

    async def set_features(
        self,
        user_id: int,
        features: list[str] | None,
    ) -> BlackList | None:
        entry = await self.get_active(user_id)
        if not entry:
            return None
        normalized_features = sorted({
            self.normalize_feature(feature)
            for feature in (features or [])
            if self.normalize_feature(feature)
        })
        return await self.update(entry.id, {"features": normalized_features})

    async def remove(self, user_id: int) -> bool:
        entry = await self.get_active(user_id)
        if not entry:
            return False
        return await self.update(
            entry.id,
            {"deleted_at": datetime.now().astimezone()},
        ) is not None
