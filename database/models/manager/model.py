from sqlalchemy import Boolean, Column, func, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.models import Base


class Model(Base):
    __tablename__ = "model"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    openrouter_id = Column(Text, nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    text_default = Column(Boolean, nullable=False, default=False)
    audio_default = Column(Boolean, nullable=False, default=False)
    image_default = Column(Boolean, nullable=False, default=False)
    embedding_default = Column(Boolean, nullable=False, default=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())

    prices = relationship("ModelPrice", back_populates="model")
