from sqlalchemy import Column, func, Integer, String, text, Text, TIMESTAMP, UUID
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
    last_att_profile_pic = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="sender")
    remembers = relationship("Remember", back_populates="user")
