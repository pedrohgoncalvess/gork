from sqlalchemy import (
    Column, Integer, String, Text,
    TIMESTAMP, func, ForeignKey,
    UUID, text, BOOLEAN
)
from sqlalchemy.orm import relationship

from database.models import Base


class Message(Base):
    __tablename__ = "message"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)
    ext_id = Column(UUID, unique=True, nullable=False, server_default=text("uuid_generate_v4()"))

    message_id = Column(String(255), unique=True, nullable=False)

    user_id = Column(Integer, ForeignKey("base.user.id"))

    group_id = Column(Integer, ForeignKey("base.group.id"))

    content = Column(Text)
    created_at = Column(TIMESTAMP, nullable=False)
    is_favorite = Column(BOOLEAN, default=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, onupdate=func.now())
    deleted_at = Column(TIMESTAMP)

    sender = relationship("User", back_populates="messages")
    group = relationship("Group", back_populates="messages")
