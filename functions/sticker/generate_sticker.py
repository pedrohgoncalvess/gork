import base64
from io import BytesIO

from PIL import Image

from external.evolution import download_image
from functions.sticker import add_caption_to_image


async def generate_sticker(webhook_event: dict, caption_text: str) -> str:
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]

    message_data = event_data["message"]
    quoted_message = event_data["contextInfo"].get("stanzaId", "")

    if message_data.get("imageMessage"):
        image_base64 = await download_image(message_id)
    elif quoted_message:
        image_base64 = await download_image(quoted_message)
    else:
        return ""
    image_bytes = base64.b64decode(image_base64)

    img = Image.open(BytesIO(image_bytes))
    img.thumbnail((512, 512), Image.Resampling.LANCZOS)

    if img.mode != 'RGBA':
        img = img.convert('RGBA')

    if caption_text:
        img = add_caption_to_image(img, caption_text)

    buffer = BytesIO()
    img.save(buffer, format='WEBP', quality=95)
    buffer.seek(0)
    webp_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

    return webp_base64