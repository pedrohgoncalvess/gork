from sqlalchemy import (
    Column, Integer, String, DECIMAL, ForeignKey,
    TIMESTAMP, func, text, UUID
)
from pgvector.sqlalchemy import Vector

from database.models import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)
    ext_id = Column(UUID, unique=True, nullable=False, server_default=text("uuid_generate_v4()"))

    name = Column(String(150), nullable=False)
    message_id = Column(Integer, ForeignKey("content.message.id"), nullable=True)
    image_embedding = Column(Vector(1024), nullable=False)
    name_embedding = Column(Vector(1024), nullable=False)

    bucket = Column(String(30), nullable=False)
    path = Column(String(200), nullable=False)

    format = Column(String(20))
    size = Column(DECIMAL)

    inserted_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, onupdate=func.now())
    deleted_at = Column(TIMESTAMP)
