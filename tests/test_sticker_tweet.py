import base64
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw

from api.routes.webhook.evolution.handles.image import handle_sticker_command
from api.routes.webhook.evolution.handles.image.sticker_tweet import (
    _fit_text, _width, render_tweet_sticker,
)
from api.routes.webhook.evolution.handles.social import (
    TwitterCardDownloadResult, download_twitter_card,
)
from services import parse_params


URL = "https://x.com/usuario/status/12345"


def image_bytes(size=(800, 400), color="blue"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class TweetRenderingTests(unittest.TestCase):
    def test_card_has_sticker_dimensions_transparency_and_photo(self):
        payload = base64.b64decode(render_tweet_sticker(TwitterCardDownloadResult(
            text="Olá, mundo!", author_name="Maria", author_handle="maria",
            avatar_bytes=image_bytes((80, 80), "red"), photo_bytes=image_bytes(),
        )))
        with Image.open(BytesIO(payload)) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(image.size, (512, 512))
            self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)
            self.assertTrue(any(b > 200 and r < 50 for r, g, b, a in image.convert("RGBA").getdata()))
        self.assertLessEqual(len(payload), 100 * 1024)

    def test_long_text_and_unbroken_url_fit_and_end_with_ellipsis(self):
        draw = ImageDraw.Draw(Image.new("RGBA", (512, 512)))
        font, line_height, lines = _fit_text(draw, "https://example.com/" + "a" * 2000, 440, 208)
        self.assertLessEqual(len(lines) * line_height, 208)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(_width(draw, line, font) <= 440 for line in lines))

    def test_preserves_case_paragraphs_and_renders_emoji(self):
        draw = ImageDraw.Draw(Image.new("RGBA", (512, 512)))
        _, _, lines = _fit_text(draw, "Olá Mundo\n\nSegunda linha 😊", 440, 340)
        self.assertEqual(lines, ["Olá Mundo", "", "Segunda linha 😊"])
        self.assertTrue(render_tweet_sticker(TwitterCardDownloadResult(
            text="Olá Mundo 😊 👨‍👩‍👧‍👦", author_name="João", author_handle="joao",
        )))

    def test_invalid_optional_images_do_not_break_text_card(self):
        payload = render_tweet_sticker(TwitterCardDownloadResult(
            text="Texto sem foto", author_name="Maria", author_handle="maria",
            avatar_bytes=b"invalid", photo_bytes=b"invalid",
        ))
        self.assertTrue(payload)

    def test_portrait_and_landscape_photos_stay_within_canvas(self):
        for size in ((100, 1000), (1000, 100)):
            with self.subTest(size=size):
                result = render_tweet_sticker(TwitterCardDownloadResult(
                    text="Texto " * 200, author_name="Nome " * 50,
                    author_handle="usuario" * 40, photo_bytes=image_bytes(size),
                ))
                with Image.open(BytesIO(base64.b64decode(result))) as image:
                    bounds = image.convert("RGBA").getbbox()
                    self.assertGreaterEqual(bounds[1], 0)
                    self.assertLessEqual(bounds[3], 512)


class TweetCardDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_only_tweet_keeps_author_and_paragraphs(self):
        with patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                   new=AsyncMock(return_value={"text": "Olá\nMundo", "user": {"name": "Maria", "screen_name": "maria"}})):
            result = await download_twitter_card(URL)
        self.assertIsNone(result.error)
        self.assertEqual(result.text, "Olá\nMundo")
        self.assertEqual(result.author_name, "Maria")
        self.assertEqual(result.author_handle, "maria")

    async def test_fetches_photo_and_avatar_without_downloading_video(self):
        status = {"text": "texto", "user": {"profile_image_url_https": "https://pbs.twimg.com/avatar.jpg"},
                  "extended_entities": {"media": [{"type": "video", "media_url_https": "https://pbs.twimg.com/preview.jpg"}]}}
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status", new=AsyncMock(return_value=status)),
            patch("api.routes.webhook.evolution.handles.social._download_twitter_photo", new=AsyncMock(return_value=(b"image", None))) as download,
            patch("api.routes.webhook.evolution.handles.social._download_twitter_video", new=AsyncMock()) as video,
        ):
            result = await download_twitter_card(URL)
        self.assertEqual(download.await_count, 2)
        self.assertEqual(result.avatar_bytes, b"image")
        self.assertEqual(result.photo_bytes, b"image")
        video.assert_not_awaited()

    async def test_optional_image_failure_keeps_text(self):
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status", new=AsyncMock(return_value={
                "text": "texto", "user": {"profile_image_url_https": "https://pbs.twimg.com/avatar.jpg"}})),
            patch("api.routes.webhook.evolution.handles.social._download_twitter_photo", new=AsyncMock(return_value=(None, "failed"))),
        ):
            result = await download_twitter_card(URL)
        self.assertIsNone(result.error)
        self.assertIsNone(result.avatar_bytes)

    async def test_photo_only_tweet_succeeds(self):
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status", new=AsyncMock(return_value={
                "mediaDetails": [{"type": "photo", "media_url_https": "https://pbs.twimg.com/photo.jpg"}]})),
            patch("api.routes.webhook.evolution.handles.social._download_twitter_photo", new=AsyncMock(return_value=(b"photo", None))),
        ):
            result = await download_twitter_card(URL)
        self.assertIsNone(result.error)
        self.assertIsNone(result.text)
        self.assertEqual(result.photo_bytes, b"photo")

    async def test_does_not_attach_quoted_tweet_photo_to_parent_author(self):
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status", new=AsyncMock(return_value={
                "text": "Comentário", "mediaDetails": [],
                "extended_entities": {"media": [{"type": "photo", "media_url_https": "https://pbs.twimg.com/quoted.jpg"}]}})),
            patch("api.routes.webhook.evolution.handles.social._download_twitter_photo", new=AsyncMock()) as download,
        ):
            result = await download_twitter_card(URL)
        self.assertIsNone(result.photo_bytes)
        download.assert_not_awaited()

    async def test_invalid_private_or_empty_tweet_returns_error(self):
        for status in (None, {}, {"user": {"name": "Nome"}}):
            with patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status", new=AsyncMock(return_value=status)):
                self.assertTrue((await download_twitter_card(URL)).error)
        self.assertTrue((await download_twitter_card("https://example.com/status/12345")).error)


class TweetStickerCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        logger_patch = patch("api.routes.webhook.evolution.handles.image.logger", new=AsyncMock())
        logger_patch.start()
        self.addCleanup(logger_patch.stop)

    async def test_command_and_quoted_link_send_card(self):
        self.assertTrue(parse_params("!sticker :tweet")["tweet"])
        for content, context, params in (
            (f"!sticker :tweet {URL}", None, None),
            (f"@Gork !sticker :tweet={URL}?s=20", None, None),
            ("!sticker :tweet", {"text_quote": (URL, "Nome")}, None),
            ("!sticker", None, {"tweet": True, "url": URL}),
            ("!sticker", None, {"tweet": URL + "?s=20"}),
        ):
            command = SimpleNamespace(content=content, quoted_message_id=None, message_id="id")
            with (
                patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(text="texto"))) as download,
                patch("api.routes.webhook.evolution.handles.image.sticker_tweet.render_tweet_sticker", return_value="card-base64"),
                patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock()) as send,
                patch("api.routes.webhook.evolution.handles.image.download_twitter_media", new=AsyncMock()) as media,
            ):
                await handle_sticker_command("group", command, AsyncMock(), context, params)
            download.assert_awaited_once_with(URL)
            send.assert_awaited_once_with("group", "card-base64")
            media.assert_not_awaited()

    async def test_reported_command_uses_card_instead_of_video_downloader(self):
        command = SimpleNamespace(
            content="@Gork !sticker :tweet=https://x.com/gdois__/status/2095335085763371454?s=20",
            quoted_message_id=None, message_id="id",
        )
        with (
            patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(text="texto"))) as download,
            patch("api.routes.webhook.evolution.handles.image.sticker_tweet.render_tweet_sticker", return_value="card-base64"),
            patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock()) as send,
            patch("api.routes.webhook.evolution.handles.image.download_twitter_media", new=AsyncMock()) as media,
        ):
            await handle_sticker_command("group", command, AsyncMock())
        download.assert_awaited_once_with("https://x.com/gdois__/status/2095335085763371454")
        send.assert_awaited_once_with("group", "card-base64")
        media.assert_not_awaited()

    async def test_missing_link_and_failed_download_send_useful_error(self):
        for content in ("!sticker :tweet", f"!sticker :tweet {URL}"):
            command = SimpleNamespace(content=content, quoted_message_id=None, message_id="id")
            with (
                patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(error="Tweet indisponível"))),
                patch("api.routes.webhook.evolution.handles.image.send_message", new=AsyncMock()) as send,
                patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock()) as sticker,
            ):
                await handle_sticker_command("group", command, AsyncMock())
            send.assert_awaited_once()
            sticker.assert_not_awaited()

    async def test_database_quoted_message_supplies_link(self):
        command = SimpleNamespace(content="!sticker :tweet", quoted_message_id=42, message_id="id")
        with (
            patch("api.routes.webhook.evolution.handles.image.MessageRepository") as repo,
            patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(text="texto"))) as download,
            patch("api.routes.webhook.evolution.handles.image.sticker_tweet.render_tweet_sticker", return_value="card-base64"),
            patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock()) as send,
        ):
            repo.return_value.find_by_id = AsyncMock(return_value=SimpleNamespace(content=URL))
            await handle_sticker_command("group", command, AsyncMock())
        download.assert_awaited_once_with(URL)
        send.assert_awaited_once_with("group", "card-base64")

    async def test_rendering_failure_sends_error_without_sticker(self):
        command = SimpleNamespace(content=f"!sticker :tweet {URL}", quoted_message_id=None, message_id="id")
        with (
            patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(text="texto"))),
            patch("api.routes.webhook.evolution.handles.image.sticker_tweet.render_tweet_sticker", side_effect=ValueError("compression")),
            patch("api.routes.webhook.evolution.handles.image._log_image_command_error", new=AsyncMock()),
            patch("api.routes.webhook.evolution.handles.image.send_message", new=AsyncMock()) as send,
            patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock()) as sticker,
        ):
            await handle_sticker_command("group", command, AsyncMock())
        send.assert_awaited_once()
        sticker.assert_not_awaited()

    async def test_send_failure_returns_useful_message(self):
        command = SimpleNamespace(content=f"!sticker :tweet {URL}", quoted_message_id=None, message_id="id")
        with (
            patch("api.routes.webhook.evolution.handles.image.download_twitter_card", new=AsyncMock(return_value=TwitterCardDownloadResult(text="texto"))),
            patch("api.routes.webhook.evolution.handles.image.sticker_tweet.render_tweet_sticker", return_value="card-base64"),
            patch("api.routes.webhook.evolution.handles.image._log_image_command_error", new=AsyncMock()) as log_error,
            patch("api.routes.webhook.evolution.handles.image.send_message", new=AsyncMock()) as send,
            patch("api.routes.webhook.evolution.handles.image.send_sticker", new=AsyncMock(side_effect=RuntimeError("send failed"))),
        ):
            await handle_sticker_command("group", command, AsyncMock())
        self.assertEqual(log_error.await_args.args[0], "tweet_sticker_send_failed")
        self.assertIn("não consegui enviá-la", send.await_args.args[1])


if __name__ == "__main__":
    unittest.main()
