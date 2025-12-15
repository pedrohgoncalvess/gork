from sqlalchemy import (
    Column, Integer, String,
    TIMESTAMP, func, UUID, text, Text
)
from sqlalchemy.orm import relationship

from database.models import Base
from database.models.content import Message


class User(Base):
    __tablename__ = "user"
    __table_args__ = {"schema": "base"}

    id = Column(Integer, primary_key=True)
    src_id = Column(String(100), unique=True, nullable=False)
    ext_id = Column(UUID, unique=True, nullable=False, server_default=text("uuid_generate_v4()"))
    phone_number = Column(String(20))
    name = Column(String(255))
    profile_pic_path = Column(Text, nullable=True)

    inserted_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="sender")
    remembers = relationship("Remember", back_populates="user")