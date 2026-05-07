import base64
import hashlib
import io

import imagehash
from PIL import Image


def get_image_hash(base64_str: str) -> bytes:
    image_bytes = base64.b64decode(base64_str)
    return hashlib.sha256(image_bytes).digest()


def get_phash(base64_str: str) -> int:
    image_bytes = base64.b64decode(base64_str)
    img = Image.open(io.BytesIO(image_bytes))
    phash = int(str(imagehash.phash(img)), 16)
    if phash >= 2 ** 63:
        phash -= 2 ** 64
    return phash
