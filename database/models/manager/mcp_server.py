from security.types import EncryptedText, EncryptedJSON
from sqlalchemy import Boolean, Column, ForeignKey, Integer, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB

from database.models import Base


class McpServer(Base):
    __tablename__ = "mcp_server"
    __table_args__ = {"schema": "ai"}

    id = Column(Integer, primary_key=True)
    name = Column(EncryptedText('mcp_server.name', False), nullable=False)
    description = Column(EncryptedText('mcp_server.description', False), nullable=False)
    url = Column(EncryptedText('mcp_server.url', False), nullable=False)
    transport = Column(Text, nullable=False, default="streamable_http")
    enabled = Column(Boolean, nullable=False, default=True)
    settings_encrypted = Column(Text, nullable=False)
    tool_names = Column(JSONB, nullable=False, default=list)
    tools = Column(EncryptedJSON('mcp_server.tools'), nullable=False, default=list)
    timeout_seconds = Column(Integer, nullable=False, default=20)
    user_id = Column(Integer, ForeignKey("base.user.id"))
    group_id = Column(Integer, ForeignKey("base.group.id"))
    checked_at = Column(TIMESTAMP(timezone=True))
    last_error = Column(EncryptedText('mcp_server.last_error', False))
    inserted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    deleted_at = Column(TIMESTAMP(timezone=True))
