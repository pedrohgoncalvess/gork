from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, func, Integer, Text, TIMESTAMP

from database.models import Base


class Embedding(Base):
    __tablename__ = "embedding"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    term = Column(Text, nullable=False)
    embedding = Column(Vector(2560), nullable=False)

    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
