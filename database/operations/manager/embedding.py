from typing import Optional

from sqlalchemy import desc, func, select

from database.models.manager import Embedding
from database.operations import BaseRepository


class EmbeddingRepository(BaseRepository[Embedding]):
    def __init__(self, db):
        super().__init__(Embedding, db)

    @staticmethod
    def normalize_term(term: str) -> str:
        return " ".join(term.strip().lower().split())

    async def find_by_term(self, term: str) -> Optional[Embedding]:
        normalized_term = self.normalize_term(term)
        if not normalized_term:
            return None

        result = await self.db.execute(
            select(Embedding)
            .filter(func.lower(Embedding.term) == normalized_term)
            .order_by(desc(Embedding.inserted_at), desc(Embedding.id))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def insert_term(self, term: str, embedding: list[float]) -> Embedding:
        return await self.insert(
            Embedding(
                term=self.normalize_term(term),
                embedding=embedding,
            )
        )
