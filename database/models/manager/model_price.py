from sqlalchemy import Column, ForeignKey, func, Integer, Numeric, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.models import Base


class ModelPrice(Base):
    __tablename__ = "model_price"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_id = Column(Integer, ForeignKey("ai.model.id"), nullable=False, index=True)

    # OpenRouter publishes these values in USD per token/request/unit.
    prompt_price = Column(Numeric(30, 18))
    completion_price = Column(Numeric(30, 18))
    request_price = Column(Numeric(30, 18))
    image_price = Column(Numeric(30, 18))
    web_search_price = Column(Numeric(30, 18))
    internal_reasoning_price = Column(Numeric(30, 18))
    input_cache_read_price = Column(Numeric(30, 18))
    input_cache_write_price = Column(Numeric(30, 18))

    # Keeps provider-specific and future units (for example audio/video) intact.
    pricing = Column(JSONB, nullable=False)
    fetched_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    model = relationship("Model", back_populates="prices")
    interactions = relationship("Interaction", back_populates="model_price")
