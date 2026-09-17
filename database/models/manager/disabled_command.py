from sqlalchemy import Column, ForeignKey, func, Integer, String, Text, TIMESTAMP
from sqlalchemy.orm import relationship

from database.models import Base


class DisabledCommand(Base):
    __tablename__ = "disabled_command"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True)
    command = Column(String(50), nullable=False)
    user_id = Column(Integer, ForeignKey("base.user.id", ondelete="CASCADE"))
    group_id = Column(Integer, ForeignKey("base.group.id", ondelete="CASCADE"))
    message = Column(
        Text,
        nullable=False,
        default="Este comando está temporariamente desativado.",
        server_default="Este comando está temporariamente desativado.",
    )
    disabled_until = Column(TIMESTAMP(timezone=True))
    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True))

    user = relationship("User", backref="disabled_commands")
    group = relationship("Group", backref="disabled_commands")
