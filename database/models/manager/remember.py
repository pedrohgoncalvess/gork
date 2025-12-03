from sqlalchemy import Column, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.orm import relationship

from database.models import Base


class Remember(Base):
    __tablename__ = "remember"
    __table_args__ = {"schema": "manager"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("base.user.id"), nullable=True)
    group_id = Column(Integer, ForeignKey("base.group.id"), nullable=True)
    remember_at = Column(TIMESTAMP, nullable=False)
    message = Column(Text, nullable=True)
    inserted_at = Column(
        nullable=False,
        server_default="timezone('America/Sao_Paulo', now())"
    )
    updated_at = Column(TIMESTAMP, nullable=True)
    deleted_at = Column(TIMESTAMP, nullable=True)

    # Relationships
    user = relationship("User", back_populates="remembers")
    group = relationship("Group", back_populates="remembers")

    def __repr__(self):
        return f"<Remember(id={self.id}, remember_at={self.remember_at}, message={self.message[:30]}"