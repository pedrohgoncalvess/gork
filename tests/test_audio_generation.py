import shutil
from services.audio_conversion import audio_to_wav
import base64
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import wave

import httpx
import yaml

from agents.audio_generation.agent import text_to_speech
from external.openrouter import generate_speech


class AudioGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_voice_in_all_languages_and_scoped_model_resolution(self):
        module = "agents.audio_generation.agent"
        agent = SimpleNamespace(id=2, prompt="Read faithfully.")
        model = SimpleNamespace(openrouter_id="google/gemini-3.8-flash-lite-tts")
        connection = AsyncMock()
        with (
            patch(f"{module}.PgConnection", return_value=connection),
            patch(f"{module}.AgentRepository") as agents,
            patch(f"{module}.ModelConversationRepository") as models,
            patch(f"{module}.generate_speech", new=AsyncMock(return_value=b"\0" * 480)) as speech,
        ):
            agents.return_value.find_by_name = AsyncMock(return_value=agent)
            models.return_value.resolve_agent_model = AsyncMock(return_value=model)
            for language in ("pt", "en", "es"):
                result = await text_to_speech(
                    "  Olá!  ", language, user_id=7, group_id=3,
                    tone="descontraído, pausas curtas",
                )
                with wave.open(io.BytesIO(base64.b64decode(result)), "rb") as audio:
                    self.assertEqual(audio.getframerate(), 24000)
                    self.assertEqual(audio.getnchannels(), 1)
                    self.assertEqual(audio.getsampwidth(), 2)
                    self.assertEqual(audio.readframes(240), b"\0" * 480)
                payload = speech.await_args.args[0]
                self.assertEqual(payload["voice"], "Puck")
                self.assertEqual(payload["response_format"], "pcm")
                self.assertEqual(payload["input"], "Olá!")
                self.assertEqual(payload["model"], model.openrouter_id)
                self.assertIn("Read faithfully.", payload["provider"]["options"]["google-ai-studio"]["speech_metadata"]["style"])
                self.assertIn("descontraído, pausas curtas", payload["provider"]["options"]["google-ai-studio"]["speech_metadata"]["style"])
                self.assertNotIn("descontraído", payload["input"])
                models.return_value.resolve_agent_model.assert_awaited_with(agent, user_id=7, group_id=3)

    async def test_missing_agent_fails_without_local_fallback(self):
        module = "agents.audio_generation.agent"
        with (
            patch(f"{module}.PgConnection", return_value=AsyncMock()),
            patch(f"{module}.AgentRepository") as agents,
            patch(f"{module}.generate_speech", new=AsyncMock()) as speech,
        ):
            agents.return_value.find_by_name = AsyncMock(return_value=None)
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                await text_to_speech("Olá", user_id=7)
            speech.assert_not_awaited()

    async def test_invalid_text_or_language_does_not_call_provider(self):
        with patch("agents.audio_generation.agent.generate_speech", new=AsyncMock()) as speech:
            for text, language in ((" ", "pt"), ("Olá", "invalid")):
                with self.assertRaises(ValueError):
                    await text_to_speech(text, language, user_id=7)
            for tone in ("a" * 501, {"voice": "other"}):
                with self.assertRaises(ValueError):
                    await text_to_speech("Olá", user_id=7, tone=tone)
            speech.assert_not_awaited()

    async def test_dispatch_passes_scope_and_ignores_action_voice(self):
        from api.routes.webhook.waha.handles.chat import _dispatch_action
        module = "api.routes.webhook.waha.handles.chat"
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch(f"{module}.is_feature_blocked", new=AsyncMock(return_value=False)),
            patch(f"{module}.reserve_audio_action", new=AsyncMock(return_value=True)),
            patch(f"{module}.text_to_speech", new=AsyncMock(return_value="encoded")) as speech,
            patch(f"{module}.send_audio", new=AsyncMock()) as send,
        ):
            await _dispatch_action(
                action_type="audio", action={"parameters": {"text": "Oi", "language": "pt", "voice": "other", "tone": "brincalhão"}},
                remote_id="group", user=SimpleNamespace(id=7), db=Mock(),
                db_message=SimpleNamespace(message_id="request"), scheduler=None, context={}, group_id=3,
            )
        speech.assert_awaited_once_with("Oi", language="pt", user_id=7, group_id=3, tone="brincalhão")
        send.assert_awaited_once_with("group", "encoded", "request")

    async def test_speech_failure_delivers_text_instead_of_silence(self):
        from api.routes.webhook.waha.handles.chat import _dispatch_action
        module = "api.routes.webhook.waha.handles.chat"
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch(f"{module}.reserve_audio_action", new=AsyncMock(return_value=True)),
            patch(f"{module}.text_to_speech", new=AsyncMock(side_effect=RuntimeError("provider unavailable"))),
            patch(f"{module}.logger.error", new=AsyncMock()),
            patch(f"{module}.send_message", new=AsyncMock()) as send_text,
            patch(f"{module}.send_audio", new=AsyncMock()) as send_audio,
        ):
            await _dispatch_action(
                action_type="audio", action={"parameters": {"text": "Oi", "language": "pt"}},
                remote_id="dm", user=SimpleNamespace(id=7), db=Mock(),
                db_message=SimpleNamespace(message_id="request"), scheduler=None, context={}, group_id=None,
            )
        send_text.assert_awaited_once_with("dm", "Oi", "request")
        send_audio.assert_not_awaited()


class SpeechEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, response, response_format="mp3"):
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with (
            patch("external.openrouter.httpx.AsyncClient", return_value=context),
            patch("external.openrouter.get_env_var", return_value="test-key"),
            patch("external.openrouter.openrouter_logger.info", new=AsyncMock()) as log,
        ):
            result = await generate_speech({"model": "tts/model", "input": "private words", "voice": "Puck", "response_format": response_format})
        self.assertEqual(client.post.call_args.args[0], "https://openrouter.ai/api/v1/audio/speech")
        self.assertNotIn("private words", str(log.call_args))
        self.assertNotIn("test-key", str(log.call_args))
        return result

    async def test_returns_raw_mp3_without_parsing_json(self):
        response = httpx.Response(200, content=b"ID3mp3", headers={"Content-Type": "audio/mpeg", "X-Generation-Id": "gen-1"}, request=httpx.Request("POST", "https://openrouter.ai"))
        self.assertEqual(await self.request(response), b"ID3mp3")

    async def test_returns_raw_pcm_for_gemini(self):
        response = httpx.Response(200, content=b"\0" * 480, headers={"Content-Type": "audio/pcm"}, request=httpx.Request("POST", "https://openrouter.ai"))
        self.assertEqual(await self.request(response, "pcm"), b"\0" * 480)

    async def test_rejects_json_empty_audio_and_http_errors(self):
        for status, mime, content, error in (
            (200, "application/json", b'{}', RuntimeError),
            (200, "audio/mpeg", b'', RuntimeError),
            (429, "application/json", b'{}', httpx.HTTPStatusError),
        ):
            response = httpx.Response(status, content=content, headers={"Content-Type": mime}, request=httpx.Request("POST", "https://openrouter.ai"))
            with self.assertRaises(error):
                await self.request(response)


class AudioConfigurationTests(unittest.TestCase):
    def test_agent_registration_and_local_speech_dependency_removal(self):
        root = Path(__file__).parents[1]
        config = yaml.safe_load((root / "agents/agents.yaml").read_text(encoding="utf-8"))
        agent = next(item for item in config["agents"] if item["name"] == "audio-generation")
        self.assertEqual(agent["model"], "google/gemini-3.8-flash-lite-tts")
        self.assertTrue((root / agent["prompt_path"]).is_file())
        lock = (root / "uv.lock").read_text(encoding="utf-8")
        self.assertNotIn('name = "piper-tts"', lock)
        self.assertNotIn('name = "soundfile"', lock)
        self.assertIn('name = "onnxruntime"', lock)  # Background removal still needs it.

class AudioConversionTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is not installed")
    async def test_real_conversion_preserves_audio_duration_without_soundfile(self):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as source:
            source.setnchannels(2)
            source.setsampwidth(2)
            source.setframerate(8000)
            source.writeframes(b"\0" * 3200)
        converted = await audio_to_wav(buffer.getvalue())
        with wave.open(io.BytesIO(converted), "rb") as result:
            self.assertEqual(result.getnchannels(), 1)
            self.assertEqual(result.getframerate(), 16000)
            self.assertEqual(result.getsampwidth(), 2)
            self.assertAlmostEqual(len(result.readframes(100000)) / 32000, 0.1, places=2)

    async def test_empty_audio_is_rejected(self):
        with self.assertRaises(ValueError):
            await audio_to_wav(b"")
