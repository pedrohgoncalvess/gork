import base64
import json
import math
from io import BytesIO

from PIL import Image

from external.waha.media import send_file


SOUND_STICKER_MIME = "application/vnd.gork.sound-sticker+json"


async def send_sound_sticker(destination: str, webp: bytes, audio: bytes, duration: float) -> None:
    with Image.open(BytesIO(webp)) as image:
        sticker = {
            "webp": base64.b64encode(webp).decode("ascii"),
            "audio": base64.b64encode(audio).decode("ascii"),
            "seconds": math.ceil(duration),
            "width": image.width,
            "height": image.height,
            "animated": image.is_animated,
        }
    content = base64.b64encode(json.dumps(sticker, separators=(",", ":")).encode()).decode("ascii")
    await send_file(destination, "/api/sendSticker", content, "sticker.json", SOUND_STICKER_MIME)
