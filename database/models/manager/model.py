from sqlalchemy import (
    Column, Integer, Text,
    TIMESTAMP, func, Boolean, Numeric
)

from database.models import Base


class Model(Base):
    __tablename__ = "model"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    openrouter_id = Column(Text, nullable=False)
    input_price = Column(Numeric(10, 2))
    output_price = Column(Numeric(10, 2))
    text_default = Column(Boolean, nullable=False, default=False)
    audio_default = Column(Boolean, nullable=False, default=False)
    image_default = Column(Boolean, nullable=False, default=False)
    embedding_default = Column(Boolean, nullable=False, default=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())