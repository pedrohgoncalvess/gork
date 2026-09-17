import base64
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, UnidentifiedImageError

from api.routes.webhook.evolution.handles.image.sticker_static import (
    _open_image,
    _resize_cover,
    static_sticker,
)


class StaticStickerImageTests(unittest.TestCase):
    def test_cover_crop_honors_bottom_left_direction(self):
        image = Image.new("RGB", (4, 8))
        for y in range(8):
            color = (255, 0, 0) if y < 4 else (0, 0, 255)
            for x in range(4):
                image.putpixel((x, y), color)

        result = _resize_cover(image, (4, 4), "bottom-left")

        self.assertEqual(result.getpixel((0, 0)), (0, 0, 255))

    def test_cover_crop_defaults_to_center_for_invalid_direction(self):
        image = Image.new("RGB", (8, 4))
        for x in range(8):
            color = (255, 0, 0) if x < 4 else (0, 0, 255)
            for y in range(4):
                image.putpixel((x, y), color)

        default = _resize_cover(image, (4, 4))
        invalid = _resize_cover(image, (4, 4), "diagonal-maluca")

        self.assertEqual(list(invalid.getdata()), list(default.getdata()))

    def test_open_image_fully_loads_valid_payload(self):
        payload = BytesIO()
        Image.new("RGB", (4, 3), "red").save(payload, format="PNG")

        image = _open_image(payload.getvalue())

        self.assertEqual(image.size, (4, 3))
        self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_open_image_rejects_non_image_payload(self):
        with self.assertRaises(UnidentifiedImageError):
            _open_image(b'{"error":"expired profile URL"}')

    def test_open_image_rejects_empty_payload(self):
        with self.assertRaises(UnidentifiedImageError):
            _open_image(b"")


class StaticStickerFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_corrupted_profile_picture_uses_random_fallback(self):
        command = SimpleNamespace(
            quoted_message_id=1,
            content="!sticker",
            media_id=None,
            message_id="command-id",
            user_id=10,
        )
        quoted = SimpleNamespace(
            content=None,
            media_id=None,
            message_id="quoted-id",
            user_id=20,
        )
        user = SimpleNamespace(profile_pic_path="profile/user.jpeg")
        random_image = Image.new("RGB", (8, 6), "blue")

        with (
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.MessageRepository"
            ) as message_repo,
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.UserRepository"
            ) as user_repo,
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.S3Client"
            ) as s3_client,
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static._random_image",
                new=AsyncMock(return_value=random_image),
            ) as fallback,
        ):
            message_repo.return_value.find_by_id = AsyncMock(return_value=quoted)
            user_repo.return_value.find_by_id = AsyncMock(return_value=user)
            s3_client.return_value.connect = AsyncMock()
            s3_client.return_value.get_image_base64 = AsyncMock(
                return_value=base64.b64encode(b"not an image").decode()
            )

            result = await static_sticker(command, AsyncMock())

        fallback.assert_awaited_once()
        with Image.open(BytesIO(base64.b64decode(result))) as sticker:
            self.assertEqual(sticker.format, "WEBP")
            self.assertEqual(sticker.size, (512, 512))


if __name__ == "__main__":
    unittest.main()
