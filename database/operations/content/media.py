from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_, desc, select, text

from database.models.base import User
from database.models.content import Media, Message
from database.operations import BaseRepository


class MediaRepository(BaseRepository[Media]):
    def __init__(self, db):
        super().__init__(Media, db)

    async def find_by_hash(self, image_hash: bytes) -> Optional[Media]:
        result = await self.db.execute(
            select(Media).filter(Media.hash == image_hash).limit(1)
        )
        return result.scalar_one_or_none()

    async def find_by_similar_phash(
            self,
            phash: int,
            max_distance: int = 8
    ) -> Optional[Media]:
        query = text("""
            SELECT id
            FROM content.media
            WHERE phash IS NOT NULL
              AND bit_count((phash # CAST(:phash AS bigint))::bit(64)) <= :max_distance
            ORDER BY bit_count((phash # CAST(:phash AS bigint))::bit(64))
            LIMIT 1
        """)
        result = await self.db.execute(
            query,
            {"phash": phash, "max_distance": max_distance}
        )
        media_id = result.scalar_one_or_none()
        return await self.find_by_id(media_id) if media_id else None

    async def find_by_user(
            self,
            user_id: int,
            limit: int = 50,
            total: bool = False,
            inserted_at: Optional[datetime] = None
    ) -> List[dict]:
        if not inserted_at and not total:
            inserted_at = datetime.now() - timedelta(days=1)

        if total:
            inserted_at = None

        result = await self.db.execute(
            select(Media, User.name.label('user_name'))
            .join(Message, Message.media_id == Media.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.user_id == user_id,
                    Media.inserted_at > inserted_at if inserted_at else 1==1
                )
            )
            .order_by(desc(Media.inserted_at))
            .limit(limit)
        )

        return [
            {
                "id": row.Media.id,
                "ext_id": row.Media.ext_id,
                "name": row.Media.name,
                "size": float(row.Media.size),
                "inserted_at": row.Media.inserted_at,
                "type": row.Media.type,
                "path": row.Media.path,
                "user_name": row.user_name
            }
            for row in result.all()
        ]

    async def find_by_group(
            self,
            group_id: int,
            limit: int = 50,
            total: bool = False,
            inserted_at: Optional[datetime] = None
    ) -> List[dict]:
        if not inserted_at and not total:
            inserted_at = datetime.now() - timedelta(days=1)

        if total:
            inserted_at = None

        result = await self.db.execute(
            select(Media, User.name.label('user_name'))
            .join(Message, Message.media_id == Media.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.group_id == group_id,
                    Media.inserted_at > inserted_at if inserted_at else 1==1
                )
            )
            .order_by(desc(Media.inserted_at))
            .limit(limit)
        )

        return [
            {
                "id": row.Media.id,
                "ext_id": row.Media.ext_id,
                "name": row.Media.name,
                "size": float(row.Media.size),
                "inserted_at": row.Media.inserted_at,
                "type": row.Media.type,
                "path": row.Media.path,
                "user_name": row.user_name
            }
            for row in result.all()
        ]

    async def semantic_search_by_user(
            self,
            user_id: int,
            query_embedding: List[float],
            limit: int = 10,
            min_similarity: float = 0.5
    ) -> List[dict]:
        embedding_str = f"'[{','.join(map(str, query_embedding))}]'"

        query = text(f"""
            SELECT 
                content.media.id,
                content.media.ext_id,
                content.media.name,
                content.media.description,
                content.media.size,
                content.media.inserted_at,
                content.media.type as media_type,
                content.media.path,
                content.media.bucket,
                base."user".name as user_name,
                content.media.description_embedding <=> {embedding_str}::vector as distance,
                1 - (content.media.description_embedding <=> {embedding_str}::vector) as similarity
            FROM content.media
            JOIN content.message ON content.message.media_id = content.media.id
            JOIN base."user" ON content.message.user_id = base."user".id
            WHERE content.message.user_id = :user_id
              AND content.media.description_embedding IS NOT NULL
            ORDER BY distance
            LIMIT :limit
        """)

        result = await self.db.execute(
            query,
            {"user_id": user_id, "limit": limit}
        )

        rows = result.all()

        return [
            {
                "id": row.id,
                "ext_id": row.ext_id,
                "name": row.name,
                "size": float(row.size),
                "inserted_at": row.inserted_at,
                "type": row.media_type,
                "path": row.path,
                "bucket": row.bucket,
                "user_name": row.user_name,
                "similarity": float(row.similarity),
                "distance": float(row.distance),
                "matched_by": "description"
            }
            for row in rows
            if float(row.similarity) >= min_similarity
        ]

    async def semantic_search_by_group(
            self,
            group_id: int,
            query_embedding: List[float],
            limit: int = 10,
            min_similarity: float = 0.5
    ) -> List[dict]:
        result = await self.db.execute(
            select(
                Media,
                User.name.label('user_name'),
                Media.description_embedding.cosine_distance(query_embedding).label('distance')
            )
            .join(Message, Message.media_id == Media.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.group_id == group_id,
                    Media.description_embedding.is_not(None)
                )
            )
            .order_by('distance')
            .limit(limit)
        )

        return [
            {
                "id": row.Media.id,
                "ext_id": row.Media.ext_id,
                "name": row.Media.name,
                "size": float(row.Media.size),
                "inserted_at": row.Media.inserted_at,
                "type": row.Media.type,
                "path": row.Media.path,
                "bucket": row.Media.bucket,
                "user_name": row.user_name,
                "similarity": 1 - float(row.distance),
                "distance": float(row.distance)
            }
            for row in result.all()
            if (1 - float(row.distance)) >= min_similarity
        ]
