from sqlalchemy import (
    Column, Integer, Text,
    TIMESTAMP, func, ForeignKey
)
from sqlalchemy.orm import relationship

from database.models import Base


class Interaction(Base):
    __tablename__ = "interaction"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("manager.model.id"), nullable=False)
    command_id = Column(Integer, ForeignKey("manager.command.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("manager.agent.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("base.group.id"))
    user_prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    system_behavior = Column(Text)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    inserted_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.timezone('America/Sao_Paulo', func.now()),
        nullable=False
    )

    model = relationship("Model", backref="interactions")
    command = relationship("Command", backref="interactions")
    agent = relationship("Agent", backref="interactions")
    user = relationship("User", backref="interactions")