import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from api.routes.webhook.evolution.handles.social import (
    TwitterMediaDownloadResult,
    _extract_twitter_text,
    _find_twitter_photo_url,
    download_twitter_media,
    handle_twitter_command,
)


PHOTO_STATUS = {
    "full_text": "Uma legenda do tweet https://t.co/photo",
    "extended_entities": {
        "media": [
            {
                "type": "photo",
                "url": "https://t.co/photo",
                "media_url_https": "https://pbs.twimg.com/media/example.jpg",
            }
        ]
    },
}

VIDEO_STATUS = {
    "text": "Vídeo do quote",
    "mediaDetails": [{
        "type": "video",
        "video_info": {"variants": [
            {"content_type": "video/mp4", "bitrate": 100, "url": "https://video.twimg.com/own-low.mp4"},
            {"content_type": "video/mp4", "bitrate": 200, "url": "https://video.twimg.com/own.mp4"},
        ]},
    }],
    "quoted_tweet": PHOTO_STATUS,
}


class TwitterMetadataTests(unittest.TestCase):
    def test_ignores_nested_quoted_status_photo(self):
        self.assertIsNone(_find_twitter_photo_url({
            "text": "Comentário", "quoted_status": PHOTO_STATUS,
        }))

    def test_empty_own_media_overrides_merged_syndication_media(self):
        for own_media in ({"mediaDetails": []}, {}):
            with self.subTest(own_media=own_media):
                status = {**PHOTO_STATUS, **own_media, "quoted_tweet": PHOTO_STATUS}
                self.assertIsNone(_find_twitter_photo_url(status))

    def test_extracts_tweet_text_without_media_shortlink(self):
        self.assertEqual(_extract_twitter_text(PHOTO_STATUS), "Uma legenda do tweet")

    def test_finds_first_photo_url(self):
        self.assertEqual(
            _find_twitter_photo_url(PHOTO_STATUS),
            "https://pbs.twimg.com/media/example.jpg",
        )


class TwitterDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_prefers_video_when_available(self):
        with (
            patch(
                "api.routes.webhook.evolution.handles.social._download_twitter_video",
                new=AsyncMock(return_value=(b"video", "texto", None)),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                new=AsyncMock(return_value=VIDEO_STATUS),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social._download_twitter_photo",
                new=AsyncMock(),
            ) as photo_download,
        ):
            result = await download_twitter_media(
                "https://x.com/usuario/status/12345"
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.media_type, "video")
        self.assertEqual(result.media_bytes, b"video")
        self.assertEqual(result.text, "Vídeo do quote")
        photo_download.assert_not_awaited()

    async def test_falls_back_to_photo_when_no_video_exists(self):
        with (
            patch(
                "api.routes.webhook.evolution.handles.social._download_twitter_video",
                new=AsyncMock(return_value=(None, None, "No video")),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                new=AsyncMock(return_value=PHOTO_STATUS),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social._download_twitter_photo",
                new=AsyncMock(return_value=(b"photo", None)),
            ) as photo_download,
        ):
            result = await download_twitter_media(
                "https://twitter.com/usuario/status/12345"
            )

        self.assertTrue(result.is_success)
        self.assertEqual(result.media_type, "image")
        self.assertEqual(result.media_bytes, b"photo")
        self.assertEqual(result.text, "Uma legenda do tweet")
        photo_download.assert_awaited_once_with(
            "https://pbs.twimg.com/media/example.jpg"
        )

    async def test_quote_with_own_photo_never_downloads_quoted_video(self):
        status = deepcopy(PHOTO_STATUS)
        status["mediaDetails"] = status["extended_entities"]["media"].copy()
        quoted_video = VIDEO_STATUS["mediaDetails"][0]
        status["quoted_tweet"] = {"mediaDetails": [quoted_video]}
        status["extended_entities"]["media"].append(quoted_video)
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                  new=AsyncMock(return_value=status)) as fetch,
            patch("api.routes.webhook.evolution.handles.social._download_twitter_video",
                  new=AsyncMock(return_value=(b"wrong-video", None, None))) as video,
            patch("api.routes.webhook.evolution.handles.social._download_twitter_photo",
                  new=AsyncMock(return_value=(b"own-photo", None))) as photo,
        ):
            result = await download_twitter_media("https://x.com/usuario/status/12345/photo/1")
        fetch.assert_awaited_once_with("12345")
        video.assert_not_awaited()
        photo.assert_awaited_once_with("https://pbs.twimg.com/media/example.jpg")
        self.assertEqual(result.media_bytes, b"own-photo")
        self.assertEqual(result.media_type, "image")

    async def test_quote_video_downloads_only_own_stream(self):
        with (
            patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                  new=AsyncMock(return_value=VIDEO_STATUS)),
            patch("api.routes.webhook.evolution.handles.social._download_twitter_video",
                  new=AsyncMock(return_value=(b"own-video", None, None))) as video,
        ):
            result = await download_twitter_media("https://x.com/usuario/status/12345")
        video.assert_awaited_once_with("https://video.twimg.com/own.mp4")
        self.assertEqual(result.media_bytes, b"own-video")

    async def test_quote_without_own_media_returns_error(self):
        for quote_key in ("quoted_tweet", "quoted_status"):
            with (
                self.subTest(quote_key=quote_key),
                patch("api.routes.webhook.evolution.handles.social._fetch_twitter_status",
                      new=AsyncMock(return_value={"text": "Comentário", quote_key: VIDEO_STATUS,
                                                 "mediaDetails": []})),
                patch("api.routes.webhook.evolution.handles.social._download_twitter_video",
                      new=AsyncMock()) as video,
                patch("api.routes.webhook.evolution.handles.social._download_twitter_photo",
                      new=AsyncMock()) as photo,
            ):
                result = await download_twitter_media("https://x.com/usuario/status/12345")
            self.assertFalse(result.is_success)
            self.assertEqual(result.error, "Nenhuma mídia encontrada")
            self.assertEqual(result.text, "Comentário")
            video.assert_not_awaited()
            photo.assert_not_awaited()


class TwitterCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_twitter_command_sends_video(self):
        result = TwitterMediaDownloadResult(b"video", "video", None, "texto")
        with (
            patch(
                "api.routes.webhook.evolution.handles.social.download_twitter_media",
                new=AsyncMock(return_value=result),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social.send_video",
                new=AsyncMock(),
            ) as send_video,
        ):
            await handle_twitter_command(
                "group-id",
                "!twitter https://x.com/usuario/status/12345",
                "message-id",
            )

        send_video.assert_awaited_once()

    async def test_twitter_command_sends_image(self):
        result = TwitterMediaDownloadResult(b"photo", "image", None, "texto")
        with (
            patch(
                "api.routes.webhook.evolution.handles.social.download_twitter_media",
                new=AsyncMock(return_value=result),
            ),
            patch(
                "api.routes.webhook.evolution.handles.social.send_image",
                new=AsyncMock(),
            ) as send_image,
        ):
            await handle_twitter_command(
                "group-id",
                "!twitter https://twitter.com/usuario/status/12345",
                "message-id",
            )

        send_image.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
