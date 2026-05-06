from sqlalchemy import Boolean, Column, func, Integer, String, TIMESTAMP

from database.models import Base


class WhiteList(Base):
    __tablename__ = "white_list"
    __table_args__ = {"schema": "base"}

    id = Column(Integer, primary_key=True)

    sender_type = Column(String(5), nullable=False)  # 'user' ou 'group'
    sender_id = Column(Integer, nullable=False)      # id na tabela identity
    is_admin = Column(Boolean, nullable=False, default=False)

    inserted_at = Column(TIMESTAMP, server_default=func.now())
    deleted_at = Column(TIMESTAMP)
