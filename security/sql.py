"""Explicit encryption types for raw SQL parameters and results."""
from sqlalchemy import ARRAY, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

from security.crypto import encrypt, decrypt
from security.types import EncryptedText


def map_identities(value, operation):
    if isinstance(value, str):
        return operation(value, 'identity', True) if operation is encrypt else operation(value, 'identity')
    if isinstance(value, list):
        return [map_identities(item, operation) for item in value]
    if isinstance(value, dict):
        return {map_identities(key, operation): map_identities(item, operation) for key, item in value.items()}
    return value


class IdentityJSON(TypeDecorator):
    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return map_identities(value, encrypt) if value is not None else None

    def process_result_value(self, value, dialect):
        return map_identities(value, decrypt) if value is not None else None


def typed_text(sql, *, binds=None, columns=None):
    statement = text(sql)
    for name, type_ in (binds or {}).items():
        if name in statement._bindparams:
            statement = statement.bindparams(bindparam(name, type_=type_))
    if columns:
        return statement.columns(**columns)
    return statement


def ban_text(sql):
    """Keep JSON identity membership and indexed equality operational."""
    identity = EncryptedText('identity', True)
    binds = {'target': identity, 'voter': identity,
             'name': EncryptedText('ban.target_name')}
    if 'CAST(:aliases AS text[])' in sql:
        binds['aliases'] = ARRAY(identity)
    # JSON parameters are serialized by their SQLAlchemy type, rather than callers.
    if 'CAST(:aliases AS jsonb)' in sql:
        binds['aliases'] = IdentityJSON()
    binds['electorate'] = IdentityJSON()
    cols = {'target_name': EncryptedText('ban.target_name'), 'target_id': identity,
            'voter_id': identity, 'target_aliases': IdentityJSON(), 'electorate': IdentityJSON(),
            'group_name': EncryptedText('group.name', True)}
    return typed_text(sql, binds=binds, columns=cols if sql.lstrip().upper().startswith(('SELECT', 'WITH')) else None)
