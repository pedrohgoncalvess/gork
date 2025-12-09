from sqlalchemy import (
    Column, Integer, String, DECIMAL, ForeignKey,
    TIMESTAMP, func
)
from sqlalchemy.orm import relationship

from database.models import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)

    name = Column(String(150), nullable=False)
    message_id = Column(Integer, ForeignKey("content.message.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=True)

    bucket = Column(String(30), nullable=False)
    sub_path = Column(String(200), nullable=False)

    type = Column(String(20))
    size = Column(DECIMAL)

    inserted_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP, onupdate=func.now())
    deleted_at = Column(TIMESTAMP)
