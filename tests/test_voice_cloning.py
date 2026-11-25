import base64
import io
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import wave

import httpx
import yaml

from agents.voice_cloning.agent import clone_voice
from external.openrouter import SpeechAudio, generate_speech_audio
from services.action_rate_limiter import reserve_audio_action
from voices.catalog import VoiceSelectionError, extract_reference, init_voices, reference_path, voice_name


class VoiceCloningTests(unittest.IsolatedAsyncioTestCase):
    async def test_reference_and_scoped_agent_model_with_actual_pcm_rate(self):
        module = "agents.voice_cloning.agent"
        agent = SimpleNamespace(id=9, prompt="This must not be sent")
        voice = SimpleNamespace(file_path="someone.mp4", start_seconds=10, duration_seconds=180)
        with (
            patch(f"{module}.PgConnection", return_value=AsyncMock()),
            patch(f"{module}.VoiceRepository") as voices,
            patch(f"{module}.AgentRepository") as agents,
            patch(f"{module}.ModelConversationRepository") as models,
            patch(f"{module}.reference_path", return_value=Path("someone.mp4")),
            patch(f"{module}.extract_reference", return_value=b"RIFF-reference") as extract,
            patch(f"{module}.generate_speech_audio", new=AsyncMock(return_value=SpeechAudio(b"\0" * 1000, 44100, 1))) as speech,
        ):
            voices.return_value.find_available = AsyncMock(return_value=voice)
            agents.return_value.find_by_name = AsyncMock(return_value=agent)
            models.return_value.resolve_agent_model = AsyncMock(return_value=SimpleNamespace(openrouter_id="heygen/heygen-voice-1"))
            result = await clone_voice("Olá!", "Sílvio Santos", user_id=7, group_id=3)
        agents.return_value.find_by_name.assert_awaited_once_with("voice-cloning")
        voices.return_value.find_available.assert_awaited_once_with("silvio_santos")
        models.return_value.resolve_agent_model.assert_awaited_once_with(agent, user_id=7, group_id=3)
        extract.assert_called_once_with(Path("someone.mp4"), 10, 180)
        payload = speech.await_args.args[0]
        self.assertNotIn("voice", payload)
        self.assertNotIn("instructions", payload)
        self.assertEqual(payload["input"], "Olá!")
        self.assertTrue(payload["input_references"][0]["input_audio"]["data"].startswith("data:audio/wav;base64,"))
        with wave.open(io.BytesIO(base64.b64decode(result))) as wav:
            self.assertEqual(wav.getframerate(), 44100)
            self.assertEqual(wav.getnframes(), 500)

    async def test_unknown_voice_does_not_call_provider(self):
        module = "agents.voice_cloning.agent"
        with (
            patch(f"{module}.PgConnection", return_value=AsyncMock()),
            patch(f"{module}.VoiceRepository") as voices,
            patch(f"{module}.generate_speech_audio", new=AsyncMock()) as speech,
        ):
            voices.return_value.find_available = AsyncMock(return_value=None)
            with self.assertRaises(VoiceSelectionError):
                await clone_voice("Oi", "missing", user_id=1)
        speech.assert_not_awaited()

    async def test_command_passes_voice_and_removes_it_from_spoken_text(self):
        from api.routes.webhook.waha.handles.audio import handle_audio_command
        for syntax in (':voice=bolsonaro', ':voice bolsonaro', ':voice="bolsonaro"'):
            with patch("api.routes.webhook.waha.handles.chat._dispatch_action", new=AsyncMock()) as dispatch:
                await handle_audio_command(
                    f'!audio {syntax} Eu amo a Dua Lipa, tá ok?', "chat", SimpleNamespace(id=1),
                    SimpleNamespace(message_id="request"), None, None, {},
                )
            params = dispatch.await_args.kwargs["action"]["parameters"]
            self.assertEqual(params["voice"], "bolsonaro")
            self.assertEqual(params["text"], "Eu amo a Dua Lipa, tá ok?")

    async def test_pcm_metadata_preserved(self):
        response = httpx.Response(200, content=b"\0" * 100,
            headers={"Content-Type": "audio/pcm;rate=44100;channels=1"},
            request=httpx.Request("POST", "https://openrouter.ai"))
        context = AsyncMock()
        context.__aenter__.return_value.post.return_value = response
        with patch("external.openrouter.httpx.AsyncClient", return_value=context), patch("external.openrouter.get_env_var", return_value="key"):
            audio = await generate_speech_audio({"model": "heygen/test", "response_format": "pcm"})
        self.assertEqual(audio.sample_rate, 44100)

    async def test_zero_cooldown_never_touches_redis(self):
        with patch("services.action_rate_limiter._client") as redis:
            self.assertTrue(await reserve_audio_action("group:1"))
            self.assertTrue(await reserve_audio_action("group:1"))
        redis.assert_not_called()


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for MP4 references")
    def test_real_mp4_audio_track_is_extracted_to_mono_wav(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "voice sample.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                "-f", "lavfi", "-i", "sine=frequency=400:duration=1.5",
                "-c:a", "aac", str(source),
            ], check=True, capture_output=True)
            data = extract_reference(source, 0.25, 1)
            with wave.open(io.BytesIO(data)) as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertEqual(wav.getframerate(), 24000)
                self.assertEqual(wav.getsampwidth(), 2)
                self.assertGreater(len(wav.readframes(24000)), 40000)

    async def test_startup_reads_new_mp4_and_skips_missing_reference(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "new.mp4").write_bytes(b"media")
            (root / "metadata.yaml").write_text(yaml.safe_dump({"voices": [
                {"name": "Nova Voz", "path": "new.mp4", "duration_seconds": 180},
                {"name": "missing", "path": "missing.mp4"},
            ]}), encoding="utf-8")
            with (
                patch("voices.catalog.PgConnection", return_value=AsyncMock()),
                patch("voices.catalog.VoiceRepository") as repo,
                patch("voices.catalog.extract_reference", return_value=b"wav"),
                patch("voices.catalog.logger.info", new=AsyncMock()),
                patch("voices.catalog.logger.error", new=AsyncMock()),
            ):
                repo.return_value.sync = AsyncMock()
                self.assertEqual(await init_voices(root), 1)
            entries = repo.return_value.sync.await_args.args[0]
            self.assertEqual(entries[0]["name"], "nova_voz")
            self.assertEqual(entries[0]["file_path"], "new.mp4")
            self.assertEqual(entries[0]["duration_seconds"], 180)

    def test_paths_stay_inside_catalog_and_name_normalization(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for invalid in ("../outside.mp4", "https://example.com/a.mp4", "file.txt"):
                with self.assertRaises(ValueError):
                    reference_path(invalid, root)
        self.assertEqual(voice_name("Faustão"), "faustao")

    async def test_agent_registration_without_a_prompt_file(self):
        from agents.init import init_agents
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agents").mkdir()
            (root / "agents" / "agents.yaml").write_text(yaml.safe_dump({"agents": [
                {"name": "voice-cloning", "model": "heygen/heygen-voice-1"},
            ]}), encoding="utf-8")
            with (
                patch("agents.init.project_root", root),
                patch("agents.init.PgConnection", return_value=AsyncMock()),
                patch("agents.init.AgentRepository") as agents,
                patch("agents.init.ModelRepository") as models,
                patch("agents.init.logger.error", new=AsyncMock()) as error,
                patch("agents.init.logger.info", new=AsyncMock()),
            ):
                models.return_value.find_all = AsyncMock(return_value=[SimpleNamespace(id=12, openrouter_id="heygen/heygen-voice-1")])
                agents.return_value.upsert_by_name = AsyncMock()
                await init_agents()
            agents.return_value.upsert_by_name.assert_awaited_once_with(
                name="voice-cloning", prompt="", model_id=12, response_format=None,
            )
            error.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
