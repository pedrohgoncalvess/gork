import base64
import math
from io import BytesIO

import httpx
from PIL import Image

from external.waha.base import chat_id
from utils import get_env_var


async def send_sound_sticker(destination: str, webp: bytes, audio: bytes, duration: float) -> None:
    url = get_env_var("SOUND_STICKER_URL")
    token = get_env_var("SOUND_STICKER_TOKEN")
    if not url or not token:
        raise RuntimeError("Sound sticker transport is unavailable")
    with Image.open(BytesIO(webp)) as image:
        width, height = image.size
        animated = image.is_animated
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            url.rstrip("/") + "/sticker",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "chat": chat_id(destination),
                "webp": base64.b64encode(webp).decode("ascii"),
                "audio": base64.b64encode(audio).decode("ascii"),
                "seconds": math.ceil(duration),
                "width": width,
                "height": height,
                "animated": animated,
            },
        )
        response.raise_for_status()
