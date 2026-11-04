from sqlalchemy import Boolean, Column, Float, Integer, Text, TIMESTAMP, func

from database.models import Base


class Voice(Base):
    __tablename__ = "voice"
    __table_args__ = {"schema": "content"}

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    display_name = Column(Text, nullable=False)
    file_path = Column(Text, nullable=False)
    language = Column(Text, nullable=False, default="pt")
    start_seconds = Column(Float, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=False, default=180)
    source_url = Column(Text)
    active = Column(Boolean, nullable=False, default=True)
    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
