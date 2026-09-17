from sqlalchemy import Column, ForeignKey, func, Integer, Numeric, Text, TIMESTAMP
from sqlalchemy.orm import relationship

from database.models import Base


class Interaction(Base):
    __tablename__ = "interaction"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_price_id = Column(Integer, ForeignKey("ai.model_price.id"), nullable=False)
    command_id = Column(Integer, ForeignKey("manager.command.id"), nullable=True)
    agent_id = Column(Integer, ForeignKey("ai.agent.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("base.group.id"))
    user_prompt = Column(Text, nullable=False)
    response = Column(Text)
    system_behavior = Column(Text)
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer)
    actual_cost = Column(Numeric(30, 18))
    inserted_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.timezone('America/Sao_Paulo', func.now()),
        nullable=False
    )

    model_price = relationship("ModelPrice", back_populates="interactions")
    command = relationship("Command", backref="interactions")
    agent = relationship("Agent", backref="interactions")
    user = relationship("User", backref="interactions")
