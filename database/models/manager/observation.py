from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Text, TIMESTAMP, func

from database.models import Base


class Observation(Base):
    __tablename__ = "observation"
    __table_args__ = (
        CheckConstraint("(group_id IS NULL) <> (user_id IS NULL)", name="observation_scope"),
        CheckConstraint("length(btrim(content)) BETWEEN 1 AND 4000", name="observation_content_length"),
        CheckConstraint("(embedding IS NULL) = (embedding_model_id IS NULL)", name="observation_embedding_model"),
        {"schema": "manager"},
    )

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, ForeignKey("base.group.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=True)
    source_message_id = Column(Integer, ForeignKey("content.message.id", ondelete="SET NULL"))
    content = Column(Text, nullable=False)
    embedding = Column(Vector(2560), nullable=True)
    embedding_model_id = Column(Integer, ForeignKey("ai.model.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
