from typing import Optional, List
from datetime import datetime, timedelta

from sqlalchemy import select, and_, desc, text

from database.models.content import Media, Message
from database.models.base import User
from database.operations import BaseRepository


class MediaRepository(BaseRepository[Media]):

    # ==================== BUSCA SIMPLES ====================

    async def find_by_user(
            self,
            user_id: int,
            limit: int = 50,
            inserted_at: Optional[datetime] = None
    ) -> List[dict]:
        """Busca simples de mídias por usuário"""
        if not inserted_at:
            inserted_at = datetime.now() - timedelta(days=1)

        result = await self.db.execute(
            select(Media, User.name.label('user_name'))
            .join(Message, Media.message_id == Message.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.user_id == user_id,
                    Media.deleted_at.is_(None),
                    Media.inserted_at > inserted_at
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
                "format": row.Media.format,
                "path": row.Media.path,
                "user_name": row.user_name
            }
            for row in result.all()
        ]

    async def find_by_group(
            self,
            group_id: int,
            limit: int = 50,
            inserted_at: Optional[datetime] = None
    ) -> List[dict]:
        """Busca simples de mídias por grupo"""
        if not inserted_at:
            inserted_at = datetime.now() - timedelta(days=1)

        result = await self.db.execute(
            select(Media, User.name.label('user_name'))
            .join(Message, Media.message_id == Message.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.group_id == group_id,
                    Media.deleted_at.is_(None),
                    Media.inserted_at > inserted_at
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
                "format": row.Media.format,
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

        # Usa a MENOR distância (melhor match) entre name e image
        query = text(f"""
            SELECT 
                content.media.id,
                content.media.ext_id,
                content.media.name,
                content.media.size,
                content.media.inserted_at,
                content.media.format,
                content.media.path,
                content.media.bucket,
                base."user".name as user_name,
                content.media.name_embedding <=> {embedding_str}::vector as name_distance,
                content.media.image_embedding <=> {embedding_str}::vector as image_distance,
                1 - (content.media.name_embedding <=> {embedding_str}::vector) as name_similarity,
                1 - (content.media.image_embedding <=> {embedding_str}::vector) as image_similarity,
                LEAST(
                    content.media.name_embedding <=> {embedding_str}::vector,
                    content.media.image_embedding <=> {embedding_str}::vector
                ) as best_distance,
                GREATEST(
                    1 - (content.media.name_embedding <=> {embedding_str}::vector),
                    1 - (content.media.image_embedding <=> {embedding_str}::vector)
                ) as best_similarity
            FROM content.media
            JOIN content.message ON content.media.message_id = content.message.id
            JOIN base."user" ON content.message.user_id = base."user".id
            WHERE content.message.user_id = :user_id
              AND content.media.deleted_at IS NULL
            ORDER BY best_distance
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
                "format": row.format,
                "path": row.path,
                "bucket": row.bucket,
                "user_name": row.user_name,
                "name_similarity": float(row.name_similarity),
                "image_similarity": float(row.image_similarity),
                "best_similarity": float(row.best_similarity),
                "best_distance": float(row.best_distance),
                "matched_by": "name" if row.name_similarity > row.image_similarity else "image"
            }
            for row in rows
            if float(row.name_similarity) >= min_similarity or float(row.image_similarity) >= min_similarity
        ]

    async def semantic_search_by_group(
            self,
            group_id: int,
            query_embedding: List[float],
            limit: int = 10,
            min_similarity: float = 0.5
    ) -> List[dict]:
        """
        Busca semântica de imagens por grupo usando embeddings
        """
        result = await self.db.execute(
            select(
                Media,
                User.name.label('user_name'),
                Media.name_embedding.cosine_distance(query_embedding).label('distance')
            )
            .join(Message, Media.message_id == Message.id)
            .join(User, Message.user_id == User.id)
            .filter(
                and_(
                    Message.group_id == group_id,
                    Media.deleted_at.is_(None),
                    Media.name_embedding.is_not(None)
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
                "format": row.Media.format,
                "path": row.Media.path,
                "bucket": row.Media.bucket,
                "user_name": row.user_name,
                "similarity": 1 - float(row.distance),
                "distance": float(row.distance)
            }
            for row in result.all()
            if (1 - float(row.distance)) >= min_similarity
        ]

    async def semantic_search_by_image(
            self,
            user_id: Optional[int],
            group_id: Optional[int],
            image_embedding: List[float],
            limit: int = 10,
            min_similarity: float = 0.6
    ) -> List[dict]:
        query = select(
            Media,
            User.name.label('user_name'),
            Media.image_embedding.cosine_distance(image_embedding).label('distance')
        ).join(Message, Media.message_id == Message.id).join(
            User, Message.user_id == User.id
        ).filter(
            and_(
                Media.deleted_at.is_(None),
                Media.image_embedding.is_not(None)
            )
        )

        if user_id:
            query = query.filter(Message.user_id == user_id)
        if group_id:
            query = query.filter(Message.group_id == group_id)

        query = query.order_by('distance').limit(limit)
        result = await self.db.execute(query)

        return [
            {
                "id": row.Media.id,
                "ext_id": row.Media.ext_id,
                "name": row.Media.name,
                "size": float(row.Media.size),
                "inserted_at": row.Media.inserted_at,
                "format": row.Media.format,
                "path": row.Media.path,
                "bucket": row.Media.bucket,
                "user_name": row.user_name,
                "similarity": 1 - float(row.distance),
                "distance": float(row.distance)
            }
            for row in result.all()
            if (1 - float(row.distance)) >= min_similarity
        ]