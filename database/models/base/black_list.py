from sqlalchemy import ARRAY, Column, ForeignKey, func, Integer, text, Text, TIMESTAMP

from database.models import Base


class BlackList(Base):
    __tablename__ = "black_list"
    __table_args__ = {"schema": "base"}

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("base.user.id", ondelete="CASCADE"),
        nullable=False,
    )
    features = Column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(TIMESTAMP(timezone=True))
