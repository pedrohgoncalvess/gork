import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.routes.webhook.waha.handles.image import handle_sticker_command
from api.routes.webhook.waha.handles.youtube import (
    YouTubeDownloadError,
    download_youtube_video,
    extract_youtube_url,
)
from api.routes.webhook.waha.processors.common import process_commands


VIDEO_ID = "BaW_jenozKc"
WATCH_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
SHORTS_URL = f"https://www.youtube.com/shorts/{VIDEO_ID}?si=share"


class YouTubeUrlTests(unittest.TestCase):
    def test_video_links_normalize_to_one_video(self):
        for url in (WATCH_URL + "&list=playlist", SHORTS_URL, f"https://youtu.be/{VIDEO_ID}"):
            with self.subTest(url=url):
                self.assertEqual(extract_youtube_url(url), WATCH_URL)

    def test_playlists_and_lookalike_hosts_are_rejected(self):
        for url in (
            "https://www.youtube.com/playlist?list=playlist",
            f"https://www.youtube.com.example/shorts/{VIDEO_ID}",
            f"https://www.youtube.com@example.com/watch?v={VIDEO_ID}",
        ):
            with self.subTest(url=url):
                self.assertIsNone(extract_youtube_url(url))


class YouTubeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_dispatch_sends_mp4_for_a_shorts_link(self):
        def finish_download(command, **kwargs):
            self.assertEqual(command[-1], WATCH_URL)
            output = Path(command[command.index("--output") + 1].replace("%(ext)s", "mp4"))
            output.write_bytes(b"mp4")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        with (
            patch("api.routes.webhook.waha.processors.common.get_disabled_command_message",
                  new=AsyncMock(return_value=None)) as disabled,
            patch("api.routes.webhook.waha.handles.youtube.subprocess.run",
                  side_effect=finish_download),
            patch("api.routes.webhook.waha.handles.youtube.send_video",
                  new=AsyncMock()) as send,
        ):
            await process_commands(
                f"!youtube {SHORTS_URL}", "group", "message-id", SimpleNamespace(id=7),
                {}, 4, Mock(), Mock(), {}, Mock(),
            )

        self.assertEqual(disabled.await_args.kwargs["command"], "youtube")
        send.assert_awaited_once_with("group", "bXA0", "message-id")

    async def test_size_limit_is_reported_when_download_is_skipped(self):
        with patch(
            "api.routes.webhook.waha.handles.youtube.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=b"larger than max-filesize", stderr=b""),
        ):
            with self.assertRaisesRegex(YouTubeDownloadError, "16 MiB"):
                await download_youtube_video(SHORTS_URL)

    async def test_sticker_keeps_caption_and_cut_with_direct_or_quoted_short(self):
        for content, context in (
            (f"!sticker {SHORTS_URL} legenda :cut 2-5", {}),
            (f"!sticker :url {SHORTS_URL} legenda :cut 2-5", {}),
            (f'!sticker :url="{SHORTS_URL}" legenda :cut 2-5', {}),
            ("!sticker legenda :cut 2-5", {"text_quote": (SHORTS_URL, "quoted-id")}),
        ):
            with (
                self.subTest(content=content),
                patch("api.routes.webhook.waha.handles.image.download_youtube_video",
                      new=AsyncMock(return_value=b"mp4")) as download,
                patch("api.routes.webhook.waha.handles.image.sticker_animated.animated_sticker_from_bytes",
                      new=AsyncMock(return_value="webp")) as animated,
                patch("api.routes.webhook.waha.handles.image.send_animated_sticker",
                      new=AsyncMock()) as send,
            ):
                message = SimpleNamespace(
                    content=content, quoted_message_id=None, message_id="message-id",
                )
                await handle_sticker_command("group", message, Mock(), context)

                download.assert_awaited_once_with(WATCH_URL)
                self.assertEqual(animated.await_args.args[:2], (b"mp4", "legenda"))
                self.assertEqual(animated.await_args.kwargs["cut_spec"], "2-5")
                send.assert_awaited_once_with("group", "webp")
