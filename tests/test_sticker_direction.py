import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.routes.webhook.evolution.handles.image import (
    _fill_enabled,
    handle_sticker_command,
)
from api.routes.webhook.evolution.handles.image.sticker_animated import (
    _square_video_filter,
)
from api.routes.webhook.evolution.handles.image.sticker_crop import (
    normalize_fill_direction,
)


class StickerDirectionTests(unittest.TestCase):
    def test_direction_enables_fill_without_fill_parameter(self):
        self.assertTrue(_fill_enabled({"direction": "bottom-left"}))

    def test_fill_remains_disabled_without_fill_or_direction(self):
        self.assertFalse(_fill_enabled({}))

    def test_portuguese_and_reversed_aliases_are_normalized(self):
        self.assertEqual(normalize_fill_direction("baixo-esquerda"), "bottom-left")
        self.assertEqual(normalize_fill_direction("left-up"), "top-left")

    def test_invalid_direction_falls_back_to_center(self):
        self.assertEqual(normalize_fill_direction("perto-do-rosto"), "center")

    def test_ffmpeg_fill_filter_uses_requested_crop_anchor(self):
        self.assertEqual(
            _square_video_filter(512, True, "bottom-left"),
            "scale=512:512:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=512:512:0:ih-oh",
        )

    def test_ffmpeg_fill_filter_remains_centered_by_default(self):
        self.assertEqual(
            _square_video_filter(512, True),
            "scale=512:512:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=512:512:(iw-ow)/2:(ih-oh)/2",
        )


class StickerDirectionVideoTests(unittest.IsolatedAsyncioTestCase):
    async def test_quoted_video_direction_enables_fill(self):
        command = SimpleNamespace(
            quoted_message_id=None,
            content="!sticker :direction=top",
            media_id=None,
            message_id="command-id",
            user_id=10,
        )
        with (
            patch(
                "api.routes.webhook.evolution.handles.image.MessageRepository"
            ) as message_repo,
            patch(
                "api.routes.webhook.evolution.handles.image._load_source_media_bytes",
                new=AsyncMock(return_value=b"video-bytes"),
            ),
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_animated.animated_sticker_from_bytes",
                new=AsyncMock(return_value="sticker-url"),
            ) as animated_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_animated_sticker",
                new=AsyncMock(),
            ) as send_sticker,
        ):
            message_repo.return_value.find_by_id = AsyncMock(return_value=None)
            await handle_sticker_command(
                "group-id",
                command,
                AsyncMock(),
                context={"video_quote": "video-id"},
            )

        call = animated_sticker.await_args
        self.assertEqual(call.args[0], b"video-bytes")
        self.assertTrue(call.args[3])
        self.assertEqual(call.kwargs["direction"], "top")
        send_sticker.assert_awaited_once_with("group-id", "sticker-url")


if __name__ == "__main__":
    unittest.main()
