from sqlalchemy import Column, ForeignKey, func, Integer, TIMESTAMP
from sqlalchemy.orm import relationship

from database.models import Base


class ModelConversation(Base):
    __tablename__ = "model_conversation"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("base.user.id"))
    group_id = Column(Integer, ForeignKey("base.group.id"))
    agent_id = Column(Integer, ForeignKey("manager.agent.id"), nullable=False)
    model_id = Column(Integer, ForeignKey("manager.model.id"), nullable=False)

    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    user = relationship("User")
    group = relationship("Group")
    agent = relationship("Agent")
    model = relationship("Model")
