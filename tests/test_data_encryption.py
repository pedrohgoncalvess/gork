import base64
from io import BytesIO
import os
import struct
import unittest
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text
from sqlalchemy.dialects import postgresql

from security.crypto import cipher, master_key, encrypt, decrypt
from security.files import CHUNK_SIZE, MAGIC, IteratorReader, encrypt_stream, decrypt_stream
from security.sql import IdentityJSON, ban_text
from security.types import EncryptedText, EncryptedJSON


class EncryptionTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'DATA_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode()})
        self.env.start()
        master_key.cache_clear()
        cipher.cache_clear()

    def tearDown(self):
        self.env.stop()
        master_key.cache_clear()
        cipher.cache_clear()

    def test_random_messages_and_deterministic_lookup(self):
        value = 'Olá, telefone 5511999999999 🔒'
        for deterministic in (False, True):
            a = encrypt(value, 'test', deterministic)
            b = encrypt(value, 'test', deterministic)
            self.assertEqual(a == b, deterministic)
            self.assertNotIn(value, a)
            self.assertEqual(decrypt(a, 'test'), value)
            with self.assertRaises(ValueError):
                decrypt(a, 'other-field')
        self.assertIsNone(encrypt(None, 'test'))
        self.assertEqual(decrypt(encrypt('', 'test'), 'test'), '')

    def test_tamper_and_key_failures(self):
        a = encrypt('private', 'test')
        payload = bytearray(base64.urlsafe_b64decode(a.split(':', 2)[2]))
        payload[-1] ^= 1
        with self.assertRaises(ValueError):
            decrypt('gork:v1:' + base64.urlsafe_b64encode(payload).decode(), 'test')
        os.environ['DATA_ENCRYPTION_KEY'] = ''
        master_key.cache_clear()
        cipher.cache_clear()
        with self.assertRaises(RuntimeError):
            encrypt('requires a valid key', 'test')

    def test_envelope_looking_input_is_always_encrypted(self):
        value = encrypt('nested', 'test')
        self.assertEqual(decrypt(encrypt(value, 'test'), 'test'), value)
        with self.assertRaises(ValueError):
            decrypt('invalid envelope', 'test')

    def test_actual_sql_roundtrip_and_indexed_equality(self):
        engine = create_engine('sqlite://')
        metadata = MetaData()
        table = Table('secure', metadata, Column('id', Integer, primary_key=True),
                      Column('phone', EncryptedText('identity', True), unique=True),
                      Column('body', EncryptedText('body')))
        metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(table.insert().values(id=1, phone='5511999999999', body='sensitive'))
            stored = connection.execute(text('SELECT phone, body FROM secure')).one()
            self.assertNotIn('5511999999999', stored.phone)
            self.assertNotIn('sensitive', stored.body)
            self.assertEqual(connection.execute(select(table).where(table.c.phone == '5511999999999')).one().body, 'sensitive')
            connection.execute(table.update().values(body='edited'))
            self.assertEqual(connection.execute(select(table.c.body)).scalar_one(), 'edited')
        engine.dispose()

    def test_json_and_json_identity_membership(self):
        value = {'5511999999999@c.us': '987@lid'}
        codec = IdentityJSON()
        sealed = codec.process_bind_param(value, None)
        self.assertNotIn('5511999999999@c.us', sealed)
        self.assertEqual(codec.process_result_value(sealed, None), value)
        token = EncryptedText('identity', True).process_bind_param('5511999999999@c.us', None)
        self.assertIn(token, sealed)
        codec = EncryptedJSON('reference.media')
        value = {'url': 'https://secret/file', 'key': 'media-secret'}
        self.assertEqual(codec.process_result_value(codec.process_bind_param(value, None), None), value)

    def test_raw_sql_binds_and_result_columns(self):
        stmt = ban_text('SELECT target_name FROM manager.group_ban_poll WHERE target_id=:target AND target_aliases ?| CAST(:aliases AS text[])')
        compiled = stmt.compile(dialect=postgresql.dialect())
        self.assertIn('target_name', str(compiled))
        self.assertIsInstance(stmt.selected_columns.target_name.type, EncryptedText)
        binds = stmt.element._bindparams
        token = binds['target'].type.process_bind_param('5511', None)
        self.assertEqual(decrypt(token, 'identity'), '5511')
        insert = ban_text('INSERT INTO manager.group_ban_poll (target_aliases) VALUES (CAST(:aliases AS jsonb))')
        self.assertIsInstance(insert._bindparams['aliases'].type, IdentityJSON)

    def test_raw_sql_decodes_columns_by_name_even_with_other_column_types(self):
        engine = create_engine('sqlite://')
        with engine.connect() as connection:
            result = connection.execute(ban_text('SELECT :value AS target_name, 7 AS id'),
                                        {'value': encrypt('Nome privado', 'ban.target_name')}).mappings().one()
            self.assertEqual(result['target_name'], 'Nome privado')
            self.assertEqual(result['id'], 7)
        engine.dispose()

    def test_file_roundtrip_boundaries_and_randomization(self):
        for size in (0, 1, CHUNK_SIZE - 1, CHUNK_SIZE, CHUNK_SIZE + 3):
            value = os.urandom(size)
            sealed = b''.join(encrypt_stream(BytesIO(value), 'bucket/key'))
            self.assertEqual(b''.join(decrypt_stream(BytesIO(sealed), 'bucket/key')), value)
            self.assertNotEqual(sealed, b''.join(encrypt_stream(BytesIO(value), 'bucket/key')))

    def test_file_integrity_context_truncation_order_and_suffix(self):
        sealed = b''.join(encrypt_stream(BytesIO(b'a' * (CHUNK_SIZE + 2)), 'bucket/key'))
        for broken in (sealed[:-1], sealed[:-20], sealed + b'junk', sealed[:45] + bytes([sealed[45] ^ 1]) + sealed[46:]):
            with self.assertRaises((ValueError, InvalidTag)):
                b''.join(decrypt_stream(BytesIO(broken), 'bucket/key'))
        with self.assertRaises(InvalidTag):
            b''.join(decrypt_stream(BytesIO(sealed), 'bucket/other'))
        offset = len(MAGIC) + 32
        first_size = 4 + struct.unpack('>I', sealed[offset:offset+4])[0]
        second = offset + first_size
        second_size = 4 + struct.unpack('>I', sealed[second:second+4])[0]
        reordered = sealed[:offset] + sealed[second:second+second_size] + sealed[offset:second] + sealed[second+second_size:]
        with self.assertRaises(InvalidTag):
            b''.join(decrypt_stream(BytesIO(reordered), 'bucket/key'))

    def test_multipart_reader_uses_bounded_reads(self):
        plain = b'x' * (CHUNK_SIZE + 13)
        reader = IteratorReader(encrypt_stream(BytesIO(plain), 'bucket/key'))
        parts = []
        while chunk := reader.read(32768):
            parts.append(chunk)
            self.assertLessEqual(len(chunk), 32768)
        self.assertEqual(b''.join(decrypt_stream(BytesIO(b''.join(parts)), 'bucket/key')), plain)

    def test_minio_upload_seals_bytes_and_read_authenticates_them(self):
        from types import SimpleNamespace
        from s3.connection import S3Client
        captured = {}

        def put(bucket, path, reader, length, **options):
            self.assertEqual(length, -1)
            self.assertEqual(options['content_type'], 'application/octet-stream')
            parts = []
            while part := reader.read(options['part_size']):
                parts.append(part)
            captured['bytes'] = b''.join(parts)

        storage = object.__new__(S3Client)
        storage.client = SimpleNamespace(put_object=put)
        storage.put_encrypted('whatsapp', '/private/file', BytesIO(b'private attachment'))
        self.assertNotIn(b'private attachment', captured['bytes'])
        plain = b''.join(storage.decrypt_object(BytesIO(captured['bytes']), 'whatsapp', '/private/file'))
        self.assertEqual(plain, b'private attachment')


if __name__ == '__main__':
    unittest.main()
