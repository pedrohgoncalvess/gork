"""Bounded-memory, authenticated file frames with an authenticated end marker.

Each file has a fresh derived key; chunk counters are nonces under that key.
Readers authenticate each frame before releasing it and require the final frame.
"""
import os
import struct
from io import RawIOBase

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from security.crypto import derive_key

MAGIC = b"GORKENC\x01"
CHUNK_SIZE = 1024 * 1024


class IteratorReader(RawIOBase):
    """Adapt a frame iterator to MinIO's bounded multipart read interface."""
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.pending = bytearray()

    def readable(self):
        return True

    def read(self, size=-1):
        if size < 0:
            raise ValueError("Encrypted streams require bounded reads")
        while len(self.pending) < size:
            chunk = next(self.chunks, None)
            if chunk is None:
                break
            self.pending.extend(chunk)
        result = bytes(self.pending[:size])
        del self.pending[:size]
        return result


def read_exact(source, size):
    parts = bytearray()
    while len(parts) < size:
        part = source.read(size - len(parts))
        if not part:
            raise ValueError("Anexo criptografado truncado.")
        parts.extend(part)
    return bytes(parts)


def encrypt_stream(source, context):
    header = MAGIC + os.urandom(32)
    aes = AESGCM(derive_key("file", salt=header[len(MAGIC):]))
    aad = header + context.encode()
    yield header
    index = 0
    while True:
        chunk = source.read(CHUNK_SIZE)
        final = not chunk
        nonce = index.to_bytes(12, "big")
        encrypted = aes.encrypt(nonce, chunk, aad + nonce + bytes([final]))
        yield struct.pack(">I", len(encrypted)) + encrypted
        if final:
            break
        index += 1


def decrypt_stream(source, context):
    header = read_exact(source, len(MAGIC) + 32)
    if not header.startswith(MAGIC):
        raise ValueError("Formato de anexo criptografado inválido ou versão desconhecida.")
    aes = AESGCM(derive_key("file", salt=header[len(MAGIC):]))
    aad = header + context.encode()
    index = 0
    while True:
        length = struct.unpack(">I", read_exact(source, 4))[0]
        if not 16 <= length <= CHUNK_SIZE + 16:
            raise ValueError("Bloco de anexo inválido.")
        encrypted = read_exact(source, length)
        final = length == 16
        nonce = index.to_bytes(12, "big")
        plain = aes.decrypt(nonce, encrypted, aad + nonce + bytes([final]))
        if final:
            if source.read(1):
                raise ValueError("Dados extras após o fim do anexo.")
            return
        yield plain
        index += 1
