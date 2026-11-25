import base64
import json
import shutil
import subprocess
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from agents.describe_video import agent
import importlib

save_media = importlib.import_module("services.save_media")


def animation(kind="GIF", duration=500):
    output = BytesIO()
    frames = [Image.new("RGB", (32, 32), color) for color in ("red", "blue")]
    frames[0].save(output, format=kind, save_all=True, append_images=frames[1:], duration=duration, loop=0)
    return output.getvalue()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class VideoPreparationTests(unittest.TestCase):
    def test_gif_and_webp_become_valid_mp4(self):
        for kind in ("GIF", "WEBP"):
            with self.subTest(kind=kind):
                data = animation(kind)
                self.assertTrue(agent.is_animation(data))
                prepared = agent.prepare_video(data)
                self.assertIn(b"ftyp", prepared[:32])

    def test_animation_above_one_minute_is_not_encoded(self):
        with patch.object(agent.subprocess, "run") as process:
            self.assertIsNone(agent.prepare_video(animation(duration=31000)))
            process.assert_not_called()

    def test_exactly_one_minute_is_accepted(self):
        self.assertIsNotNone(agent.prepare_video(animation(duration=30000)))

    def test_video_duration_is_checked_before_encoding(self):
        for duration in ("60.001", "N/A", "nan", "0"):
            with self.subTest(duration=duration), patch.object(agent.subprocess, "run") as process:
                process.return_value.stdout = json.dumps({
                    "format": {"duration": duration}, "streams": [{"codec_type": "video"}],
                }).encode()
                self.assertIsNone(agent.prepare_video(b"fake video"))
                self.assertEqual(process.call_count, 1)

    def test_real_video_with_audio_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:size=32x32:duration=1",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                "-c:v", "libx264", "-c:a", "aac", "-y", str(source),
            ], check=True, capture_output=True, timeout=20)
            self.assertIsNotNone(agent.prepare_video(source.read_bytes()))


class DescriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_oversized_video_never_calls_model(self):
        with patch.object(agent, "prepare_video", return_value=None), patch.object(agent, "completions", new_callable=AsyncMock) as api:
            self.assertEqual(await agent.describe_video(Mock(), 1, "msg", b"video"), "")
            api.assert_not_awaited()

    async def test_native_video_input_and_usage_record(self):
        configured = SimpleNamespace(id=3, prompt="Describe", disable_system_prompt=False)
        model = SimpleNamespace(id=4, openrouter_id="google/gemini-2.5-flash-lite")
        with (
            patch.object(agent, "prepare_video", return_value=b"mp4"),
            patch.object(agent, "AgentRepository") as agents,
            patch.object(agent, "ModelConversationRepository") as models,
            patch.object(agent, "InteractionRepository") as interactions,
            patch.object(agent, "completions", new_callable=AsyncMock) as api,
        ):
            agents.return_value.find_by_name = AsyncMock(return_value=configured)
            models.return_value.resolve_agent_model = AsyncMock(return_value=model)
            interactions.return_value.create_interaction = AsyncMock()
            api.return_value = {"choices": [{"message": {"content": "Uma pessoa corre."}}], "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
            self.assertEqual(await agent.describe_video(Mock(), 1, "msg", b"video", 2), "Uma pessoa corre.")
            payload = api.call_args.args[0]
            part = payload["messages"][1]["content"][1]
            self.assertEqual(part["type"], "video_url")
            self.assertEqual(part["video_url"]["url"], "data:video/mp4;base64," + base64.b64encode(b"mp4").decode())
            self.assertEqual(interactions.return_value.create_interaction.call_args.kwargs["input_tokens"], 100)


class MediaIndexingTests(unittest.IsolatedAsyncioTestCase):
    async def save(self, kind="video", fail=False, existing=None):
        with (
            patch.object(save_media, "MediaRepository") as media,
            patch.object(save_media, "MessageRepository") as messages,
            patch.object(save_media, "UserRepository") as users,
            patch.object(save_media, "S3Client") as storage,
            patch.object(save_media, "describe_video", new_callable=AsyncMock) as describe,
            patch.object(save_media, "generate_text_embeddings", new_callable=AsyncMock) as embed,
            patch.object(save_media.logger, "warning", new_callable=AsyncMock),
        ):
            media.return_value.find_by_hash = AsyncMock(return_value=existing)
            media.return_value.insert = AsyncMock(side_effect=lambda value: SimpleNamespace(id=9, description=value.description, description_embedding=value.description_embedding))
            messages.return_value.find_by_message_id = AsyncMock(return_value=None)
            users.return_value.find_by_id = AsyncMock(return_value=SimpleNamespace(ext_id="user"))
            storage.return_value.connect = AsyncMock()
            storage.return_value.upload_bytes = AsyncMock()
            describe.return_value = "Uma pessoa corre."
            if fail:
                describe.side_effect = RuntimeError("provider unavailable")
            embed.return_value = [0.1] * 2560
            data = animation() if kind in {"image", "sticker"} else b"video"
            result = await save_media.save_media_if_new(
                Mock(), 1, "msg", "msg", kind,
                media_base64=base64.b64encode(data).decode(), media_name="media",
            )
            return result, describe.await_count, embed.await_count, storage.return_value.upload_bytes.await_count

    async def test_video_gif_and_sticker_descriptions_are_indexed(self):
        for kind in ("video", "image", "sticker"):
            with self.subTest(kind=kind):
                result, descriptions, embeddings, uploads = await self.save(kind)
                self.assertEqual(result.description, "Uma pessoa corre.")
                self.assertEqual(len(result.description_embedding), 2560)
                self.assertEqual((descriptions, embeddings, uploads), (1, 1, 1))

    async def test_provider_failure_still_stores_original(self):
        result, descriptions, embeddings, uploads = await self.save(fail=True)
        self.assertIsNone(result.description)
        self.assertIsNone(result.description_embedding)
        self.assertEqual((descriptions, embeddings, uploads), (1, 0, 1))

    async def test_duplicate_never_calls_provider(self):
        existing = SimpleNamespace(id=9)
        result, descriptions, embeddings, uploads = await self.save(existing=existing)
        self.assertIs(result, existing)
        self.assertEqual((descriptions, embeddings, uploads), (0, 0, 0))
