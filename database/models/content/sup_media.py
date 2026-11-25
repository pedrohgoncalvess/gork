from sqlalchemy import Column, func, Integer, String, Text, TIMESTAMP
from pgvector.sqlalchemy import Vector

from database.models import Base


class SupMedia(Base):
    __tablename__ = "sup_media"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    bucket = Column(String(50), nullable=False)
    path = Column(String(150), nullable=False)
    type = Column(String(10), nullable=False)
    description = Column(Text)
    description_embedding = Column(Vector(2560))

    inserted_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.timezone("America/Sao_Paulo", func.now()),
        nullable=False,
    )
