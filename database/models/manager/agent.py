from sqlalchemy import Column, ForeignKey, func, Integer, Text, TIMESTAMP

from database.models import Base


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    prompt = Column(Text, nullable=False)
    model_id = Column(Integer, ForeignKey("ai.model.id"), nullable=False)
    response_format = Column(Text, nullable=True)

    inserted_at = Column(TIMESTAMP, server_default=func.now())
