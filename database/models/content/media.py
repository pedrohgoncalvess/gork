from sqlalchemy import (
    BigInteger, Column, Integer, String, DECIMAL,
    TIMESTAMP, func, text, UUID, Text, LargeBinary
)
from pgvector.sqlalchemy import Vector

from database.models import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)
    ext_id = Column(UUID, unique=True, nullable=False, server_default=text("uuid_generate_v4()"))

    name = Column(String(150), nullable=False)
    bucket = Column(String(30), nullable=False)
    path = Column(String(200), nullable=False)
    type = Column(String(20))

    size = Column(DECIMAL)
    description = Column(Text)
    description_embedding = Column(Vector(1024), nullable=False)
    image_embedding = Column(Vector(1024), nullable=False)
    hash = Column(LargeBinary, nullable=False, unique=True)
    phash = Column(BigInteger)

    inserted_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.timezone("America/Sao_Paulo", func.now()),
        nullable=False,
    )
