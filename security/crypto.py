"""Versioned authenticated encryption. Missing or invalid keys fail closed."""
import base64
from functools import lru_cache
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PREFIX = "gork:v1:"


@lru_cache(maxsize=1)
def master_key():
    value = os.environ.get("DATA_ENCRYPTION_KEY", "")
    try:
        key = base64.b64decode(value, altchars=b"-_", validate=True)
        if len(key) != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise RuntimeError("Configure DATA_ENCRYPTION_KEY com uma chave base64 de 32 bytes; preserve a chave dos dados existentes.") from None
    return key


def derive_key(domain, length=32, salt=None):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt,
                info=("gork:v1:" + domain).encode()).derive(master_key())


@lru_cache(maxsize=128)
def cipher(domain, deterministic=False):
    return AESSIV(derive_key(domain, 64)) if deterministic else AESGCM(derive_key(domain))


def encrypt(value, domain, deterministic=False):
    if value is None:
        return None
    data = value.encode("utf-8")
    aad = (PREFIX + domain).encode()
    if deterministic:
        payload = b"s" + cipher(domain, True).encrypt(data, [aad])
    else:
        nonce = os.urandom(12)
        payload = b"g" + nonce + cipher(domain).encrypt(nonce, data, aad)
    return PREFIX + base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt(value, domain):
    if value is None:
        return None
    if not value.startswith(PREFIX):
        raise ValueError("Formato de dado criptografado inválido ou versão desconhecida.")
    try:
        payload = base64.b64decode(value[len(PREFIX):], altchars=b"-_", validate=True)
        aad = (PREFIX + domain).encode()
        if payload[:1] == b"s":
            plain = cipher(domain, True).decrypt(payload[1:], [aad])
        elif payload[:1] == b"g":
            plain = cipher(domain).decrypt(payload[1:13], payload[13:], aad)
        else:
            raise ValueError()
        return plain.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeError):
        raise ValueError("Não foi possível autenticar o dado criptografado.") from None
