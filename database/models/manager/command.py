from sqlalchemy import Column, ForeignKey, func, Integer, String, TIMESTAMP
from sqlalchemy.orm import relationship

from database.models import Base


class Command(Base):
    __tablename__ = "command"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True)
    command = Column(String(50), nullable=False)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=False)
    group_id = Column(Integer, ForeignKey("base.group.id"))

    inserted_at = Column(TIMESTAMP, server_default=func.now(), nullable=False)

    user = relationship("User", backref="commands")
    group = relationship("Group", backref="commands")
