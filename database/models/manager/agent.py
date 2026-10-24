from sqlalchemy import Boolean, Column, ForeignKey, func, Integer, Text, TIMESTAMP

from database.models import Base
from security.types import EncryptedText


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, unique=True)
    prompt = Column(EncryptedText('agent.prompt'), nullable=False)
    model_id = Column(Integer, ForeignKey("ai.model.id"), nullable=False)
    response_format = Column(Text, nullable=True)
    model_managed = Column(Boolean, nullable=False, default=False, server_default="false")
    prompt_managed = Column(Boolean, nullable=False, default=False, server_default="false")

    inserted_at = Column(TIMESTAMP, server_default=func.now())
