"""SQLAlchemy types cover ORM writes, Core inserts/upserts and typed results."""
import json

from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

from security.crypto import encrypt, decrypt


class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, domain, deterministic=False):
        super().__init__()
        self.domain = domain
        self.deterministic = deterministic

    def process_bind_param(self, value, dialect):
        return encrypt(value, self.domain, self.deterministic)

    def process_result_value(self, value, dialect):
        return decrypt(value, self.domain)


class EncryptedJSON(TypeDecorator):
    """Encrypt entire JSON payload, retaining a JSONB column for compatibility."""
    impl = JSONB
    cache_ok = True

    def __init__(self, domain):
        super().__init__()
        self.domain = domain

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(json.dumps(value), self.domain)

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(decrypt(value, self.domain))
