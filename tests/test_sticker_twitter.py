import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.routes.webhook.evolution.handles.image import handle_sticker_command
from api.routes.webhook.evolution.handles.social import TwitterMediaDownloadResult


def _command(extra_params: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        quoted_message_id=None,
        content=f"!sticker https://x.com/usuario/status/12345 :text {extra_params}".strip(),
        media_id=None,
        message_id="command-id",
        user_id=10,
    )


class TwitterStickerTests(unittest.IsolatedAsyncioTestCase):
    async def test_photo_uses_tweet_text_as_static_caption(self):
        result = TwitterMediaDownloadResult(
            b"photo-bytes",
            "image",
            None,
            "Texto original do tweet",
        )
        with (
            patch(
                "api.routes.webhook.evolution.handles.image.download_twitter_media",
                new=AsyncMock(return_value=result),
            ),
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.static_sticker",
                new=AsyncMock(return_value="webp-base64"),
            ) as static_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_sticker",
                new=AsyncMock(),
            ) as send_sticker,
        ):
            await handle_sticker_command("group-id", _command(), AsyncMock())

        self.assertEqual(
            static_sticker.await_args.kwargs["caption_text"],
            "Texto original do tweet",
        )
        self.assertEqual(
            static_sticker.await_args.kwargs["source_image_bytes"],
            b"photo-bytes",
        )
        send_sticker.assert_awaited_once_with("group-id", "webp-base64")

    async def test_video_uses_tweet_text_as_animated_caption(self):
        result = TwitterMediaDownloadResult(
            b"video-bytes",
            "video",
            None,
            "Texto original do tweet",
        )
        with (
            patch(
                "api.routes.webhook.evolution.handles.image.download_twitter_media",
                new=AsyncMock(return_value=result),
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
            await handle_sticker_command("group-id", _command(), AsyncMock())

        self.assertEqual(animated_sticker.await_args.args[0], b"video-bytes")
        self.assertEqual(
            animated_sticker.await_args.args[1],
            "Texto original do tweet",
        )
        send_sticker.assert_awaited_once_with("group-id", "sticker-url")

    async def test_twitter_video_direction_enables_fill(self):
        result = TwitterMediaDownloadResult(b"video-bytes", "video", None, None)
        with (
            patch(
                "api.routes.webhook.evolution.handles.image.download_twitter_media",
                new=AsyncMock(return_value=result),
            ),
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_animated.animated_sticker_from_bytes",
                new=AsyncMock(return_value="sticker-url"),
            ) as animated_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_animated_sticker",
                new=AsyncMock(),
            ),
        ):
            await handle_sticker_command(
                "group-id",
                _command(":direction=right"),
                AsyncMock(),
            )

        call = animated_sticker.await_args
        self.assertTrue(call.args[3])
        self.assertEqual(call.kwargs["direction"], "right")


if __name__ == "__main__":
    unittest.main()
