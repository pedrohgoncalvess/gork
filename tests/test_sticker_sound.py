import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from api.routes.webhook.waha.handles.core import clean_text, get_explicit_command_feature
from api.routes.webhook.waha.handles.image import handle_sticker_command
from api.routes.webhook.waha.handles.image.sticker_animated import animated_sticker_from_bytes
from api.routes.webhook.waha.handles.image.sticker_sound import (
    StickerAudioUnavailable,
    _sound_duration_limit,
    _webp_duration,
    deliver_sound_sticker,
    extract_sticker_audio,
    sticker_cut,
)
from api.routes.webhook.waha.handles.media_tag import handle_tag_command
from external.waha.sound_sticker import send_sound_sticker
from services.media_tags import MediaTagBusy, mark_media, pending_media_tag
from services.params import parse_params


def make_webp(animated=False):
    result = BytesIO()
    first = Image.new("RGBA", (16, 16), "red")
    options = {}
    if animated:
        options.update(save_all=True, append_images=[Image.new("RGBA", (16, 16), "blue")],
                       duration=[250, 450], loop=0)
    first.save(result, format="WEBP", **options)
    return result.getvalue()


class StickerCutTests(unittest.TestCase):
    def test_flag_and_each_cut_syntax(self):
        params = parse_params("!sticker :audio :cut=1-5 :cut-video 2- :cut-audio='1:01-1:03'")
        self.assertIs(params["audio"], True)
        self.assertEqual(sticker_cut(params, "video"), "2-")
        self.assertEqual(sticker_cut(params, "audio"), "1:01-1:03")
        shared = parse_params("!sticker :cut -46")
        self.assertEqual(sticker_cut(shared, "video"), -46)
        self.assertEqual(sticker_cut(shared, "audio"), -46)
        self.assertEqual(clean_text("!sticker :cut-video 2- :cut-audio 1:01-1:03 legenda"), "legenda")

    def test_rendered_webp_duration_and_static_limit(self):
        self.assertAlmostEqual(_webp_duration(make_webp(animated=True)), 0.7)
        self.assertEqual(_sound_duration_limit(make_webp(), None, None), 7)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for audio encoding")
    def test_extract_audio_caps_to_available_track_and_visual_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "source.wav"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 "sine=frequency=500:sample_rate=48000:duration=2", str(clip)],
                check=True, capture_output=True,
            )
            raw = clip.read_bytes()
        opus, duration = extract_sticker_audio(raw, "1.25-", 5)
        self.assertTrue(opus.startswith(b"OggS"))
        self.assertIn(b"OpusHead", opus)
        self.assertAlmostEqual(duration, 0.75, places=2)
        _, duration = extract_sticker_audio(raw, None, 0.4)
        self.assertAlmostEqual(duration, 0.4, places=2)
        with self.assertRaises(StickerAudioUnavailable):
            extract_sticker_audio(raw, "3-", 7)
        with self.assertRaises(StickerAudioUnavailable):
            extract_sticker_audio(make_webp(), None, 7)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are required")
    def test_video_with_identical_frames_still_limits_audio_to_video_cut(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "source.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=s=32x32:r=10:d=2",
                 "-f", "lavfi", "-i", "sine=duration=3", "-c:v", "mpeg4", "-c:a", "aac", str(clip)],
                check=True, capture_output=True,
            )
            raw = clip.read_bytes()
        limit = _sound_duration_limit(make_webp(), raw, "0.75-")
        self.assertAlmostEqual(limit, 1.25, places=2)
        _, duration = extract_sticker_audio(raw, "1-", limit)
        self.assertAlmostEqual(duration, 1.25, places=2)


class SoundStickerCommandTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for video encoding")
    async def test_render_video_and_extract_a_different_audio_segment(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "source.mp4"
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x64:r=20:d=2",
                 "-f", "lavfi", "-i", "sine=duration=2", "-c:v", "mpeg4", "-c:a", "aac", str(clip)],
                check=True, capture_output=True,
            )
            video = clip.read_bytes()
        webp = await animated_sticker_from_bytes(video, cut_spec="1-", return_webp=True)
        duration = _webp_duration(webp)
        self.assertIsNotNone(duration)
        self.assertAlmostEqual(duration, 1, delta=0.2)
        opus, seconds = extract_sticker_audio(video, "0-", duration)
        self.assertTrue(opus.startswith(b"OggS"))
        self.assertAlmostEqual(seconds, duration, places=2)

    async def test_transport_preserves_static_webp_and_audio_metadata(self):
        root = "external.waha.sound_sticker"
        webp = make_webp()
        with patch(root + ".send_file", new_callable=AsyncMock) as send_file:
            await send_sound_sticker("12345@lid", webp, b"audio", 2.25)
        destination, endpoint, content, filename, mimetype = send_file.await_args.args
        self.assertEqual((destination, endpoint), ("12345@lid", "/api/sendSticker"))
        self.assertEqual((filename, mimetype), ("sticker.json", "application/vnd.gork.sound-sticker+json"))
        payload = json.loads(base64.b64decode(content))
        self.assertFalse(payload["animated"])
        self.assertEqual((payload["width"], payload["height"], payload["seconds"]), (16, 16, 3))
        self.assertEqual(base64.b64decode(payload["webp"]), webp)
        self.assertEqual(base64.b64decode(payload["audio"]), b"audio")

    async def test_audio_is_opt_in_and_video_override_reaches_renderer(self):
        root = "api.routes.webhook.waha.handles.image"
        message = SimpleNamespace(
            user_id=5, message_id="video", media_id=None, quoted_message_id=None,
            content="!sticker :cut=1-5 :cut-video=2-4",
        )
        with (
            patch(root + "._load_source_media_bytes", AsyncMock(return_value=b"video")),
            patch(root + ".sticker_animated.animated_sticker_from_bytes",
                  AsyncMock(return_value="https://example.test/sticker")) as render,
            patch(root + ".send_animated_sticker", AsyncMock()) as silent,
            patch(root + ".sticker_sound.deliver_sound_sticker", AsyncMock()) as sound,
        ):
            await handle_sticker_command("chat", message, MagicMock(), {"video_message": "video"})
            self.assertEqual(render.await_args.kwargs["cut_spec"], "2-4")
            self.assertNotIn("return_webp", render.await_args.kwargs)
            silent.assert_awaited_once()
            sound.assert_not_awaited()
            message.content = "!sticker :audio :cut-audio=1-2"
            render.return_value = make_webp(True)
            await handle_sticker_command("chat", message, MagicMock(), {"video_message": "video"})
            self.assertTrue(render.await_args.kwargs["return_webp"])
            self.assertEqual(render.await_args.kwargs["cut_spec"], "0-")
            self.assertEqual(sound.await_args.args[4], b"video")
            self.assertEqual(sound.await_args.args[5]["cut-audio"], "1-2")
            self.assertEqual(silent.await_count, 1)
            message.content = "!sticker :audio=false"
            render.return_value = "https://example.test/sticker"
            await handle_sticker_command("chat", message, MagicMock(), {"video_message": "video"})
            self.assertEqual(silent.await_count, 2)
            self.assertEqual(sound.await_count, 1)

    async def test_tag_overrides_video_and_supplies_audio_to_static_sticker(self):
        root = "api.routes.webhook.waha.handles.image.sticker_sound"
        image = make_webp()
        message = SimpleNamespace(user_id=5, message_id="command")

        @asynccontextmanager
        async def tag(user_id, kind):
            self.assertEqual((user_id, kind), (5, "audio"))
            yield "tagged"

        with (
            patch(root + ".pending_media_tag", tag),
            patch(root + ".MessageRepository") as repo,
            patch(root + ".extract_sticker_audio", return_value=(b"opus", 1.5)) as extract,
            patch(root + ".get_reference", AsyncMock(return_value={"chat_id": "12345@lid"})),
            patch(root + ".send_sound_sticker", AsyncMock()) as send,
        ):
            repo.return_value.find_by_message_id = AsyncMock(return_value=None)
            loader = AsyncMock(return_value=b"tagged-audio")
            for video, sticker, duration in ((b"original-video", make_webp(True), 0.7), (None, image, 7)):
                await deliver_sound_sticker(
                    "chat", message, MagicMock(), sticker, video,
                    {"cut": "1-", "cut-audio": "2-"}, loader,
                )
                extract.assert_called_with(b"tagged-audio", "2-", duration)
                send.assert_awaited_with("12345@lid", sticker, b"opus", 1.5)


class MediaTagTests(unittest.IsolatedAsyncioTestCase):
    async def test_tag_accepts_quoted_or_attached_audio_and_rejects_other_media(self):
        root = "api.routes.webhook.waha.handles.media_tag"
        message = SimpleNamespace(user_id=7, message_id="command", created_at=datetime(2026, 11, 25))
        with patch(root + ".mark_media", AsyncMock()) as mark, patch(root + ".send_message", AsyncMock()) as send:
            await handle_tag_command("chat", message, {"image_quote": "picture"})
            mark.assert_not_awaited()
            await handle_tag_command("chat", message, {"audio_quote": "quoted"})
            mark.assert_awaited_with(7, "audio", "quoted", "command", message.created_at)
            send.assert_awaited_with("chat", "Áudio marcado.", "command")
            await handle_tag_command("chat", message, {"audio_message": "attached", "audio_quote": "quoted"})
            mark.assert_awaited_with(7, "audio", "attached", "command", message.created_at)
        self.assertEqual(get_explicit_command_feature("!TAG"), "tag")
        self.assertIsNone(get_explicit_command_feature("!tagged"))

    async def test_tag_database_scope_latest_and_consumption(self):
        db = MagicMock()
        result = MagicMock()
        db.execute = AsyncMock(return_value=result)
        factory = MagicMock()

        @asynccontextmanager
        async def transaction():
            yield db

        factory.begin = transaction
        with patch("services.media_tags.get_session_factory", return_value=factory):
            await mark_media(5, "audio", "a", "command", datetime(2026, 11, 25))
            insert, values = db.execute.await_args.args
            self.assertIn("ON CONFLICT (command_message_id) DO NOTHING", str(insert))
            self.assertEqual(values["user"], 5)

            result.mappings.return_value.first.return_value = {
                "id": 2, "consumed_at": None, "source_message_id": "newest",
            }
            async with pending_media_tag(5, "audio") as tag:
                self.assertEqual(tag, "newest")
            query, owner = db.execute.await_args_list[-2].args
            self.assertIn("WHERE user_id = :user AND kind = :kind", str(query))
            self.assertIn("ORDER BY marked_at DESC, id DESC LIMIT 1", str(query))
            self.assertEqual(owner["user"], 5)
            self.assertTrue(db.execute.await_args.args[1]["consumed"])

            with self.assertRaisesRegex(RuntimeError, "send failed"):
                async with pending_media_tag(5, "audio"):
                    raise RuntimeError("send failed")
            self.assertFalse(db.execute.await_args.args[1]["consumed"])

            result.mappings.return_value.first.return_value = {"consumed_at": datetime.now(), "source_message_id": None}
            async with pending_media_tag(5, "audio") as tag:
                self.assertIsNone(tag)

            result.mappings.return_value.first.return_value = {"consumed_at": None, "source_message_id": None}
            with self.assertRaises(MediaTagBusy):
                async with pending_media_tag(5, "audio"):
                    self.fail("The same tag cannot be sent concurrently")
