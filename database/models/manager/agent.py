from sqlalchemy import (
    Column, Integer, Text,
    TIMESTAMP, func, Boolean, Numeric
)

from database.models import Base


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    prompt = Column(Text, nullable=False)
    model_id = Column(Integer, nullable=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())