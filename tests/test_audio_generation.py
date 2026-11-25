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
from api.routes.webhook.waha.handles.audio import clean_audio_text


class AudioCommandTests(unittest.IsolatedAsyncioTestCase):
    def test_removes_commands_mentions_and_parameter_values(self):
        cases = [
            ('@5511999999999 !AUDIO !english Olá mundo! :voice="outra voz" :speed=2', 'Olá mundo!'),
            ("!audio @Gork @me :user 'Maria Silva' Bom dia :random t :duration 5", 'Bom dia'),
            ('!audio :user="Maria Silva" :random Olá !search :quality 720', 'Olá'),
            ('!audio Bom dia :tone "voz calma" :time 30min', 'Bom dia'),
            ('!audio Escreva para pessoa@example.com às 10:30! https://example.com/a',
             'Escreva para pessoa@example.com às 10:30! https://example.com/a'),
            ('!audio @5511999999999 !english :speed=2 :random', ''),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(clean_audio_text(raw), expected)

    async def test_command_synthesizes_clean_text_without_conversation_agent(self):
        from api.routes.webhook.waha.processors.common import process_commands

        module = 'api.routes.webhook.waha.handles.chat'
        for group_id, language, modifier in ((None, 'pt', ''), (3, 'en', '!ENGLISH')):
            with (
                self.subTest(group_id=group_id),
                patch('api.routes.webhook.waha.processors.common.get_disabled_command_message', new=AsyncMock(return_value=None)),
                patch('api.routes.webhook.waha.processors.common.handle_conversation_agent', new=AsyncMock()) as conversation,
                patch(f'{module}.get_disabled_command_message', new=AsyncMock(return_value=None)),
                patch(f'{module}.is_feature_blocked', new=AsyncMock(return_value=False)),
                patch(f'{module}.reserve_audio_action', new=AsyncMock(return_value=True)) as reserve,
                patch(f'{module}.text_to_speech', new=AsyncMock(return_value='encoded')) as speech,
                patch(f'{module}.send_audio', new=AsyncMock()) as send,
            ):
                await process_commands(
                    f'@5511999999999 !AUDIO {modifier} Olá mundo! :user="Maria Silva" :speed 2',
                    'chat', 'request', SimpleNamespace(id=7), {}, group_id, Mock(), None, {},
                    SimpleNamespace(message_id='request'),
                )
                speech.assert_awaited_once_with('Olá mundo!', language=language, user_id=7, group_id=group_id)
                send.assert_awaited_once_with('chat', 'encoded', 'request')
                reserve.assert_awaited_once_with('user:7' if group_id is None else 'group:3')
                conversation.assert_not_awaited()

    async def test_empty_text_does_not_consume_cooldown_or_synthesize(self):
        from api.routes.webhook.waha.handles.audio import handle_audio_command

        with (
            patch('api.routes.webhook.waha.handles.chat._dispatch_action', new=AsyncMock()) as dispatch,
            patch('api.routes.webhook.waha.handles.audio.send_message', new=AsyncMock()) as send,
        ):
            await handle_audio_command(
                '!audio @5511999999999 :speed=2 !english', 'chat', SimpleNamespace(id=7),
                SimpleNamespace(message_id='request'), Mock(), None, {},
            )
        dispatch.assert_not_awaited()
        self.assertIn('Informe o texto', send.await_args.args[1])


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

    async def test_disabled_prompt_sends_only_user_text_without_speech_instructions(self):
        module = "agents.audio_generation.agent"
        agent = SimpleNamespace(id=2, prompt="Read faithfully.", disable_system_prompt=True)
        with (
            patch(f"{module}.PgConnection", return_value=AsyncMock()),
            patch(f"{module}.AgentRepository") as agents,
            patch(f"{module}.ModelConversationRepository") as models,
            patch(f"{module}.generate_speech", new=AsyncMock(return_value=b"\0" * 480)) as speech,
        ):
            agents.return_value.find_by_name = AsyncMock(return_value=agent)
            models.return_value.resolve_agent_model = AsyncMock(return_value=SimpleNamespace(openrouter_id="test/audio"))
            await text_to_speech("Olá", user_id=7, tone="calmo")
        payload = speech.await_args.args[0]
        self.assertEqual(payload["input"], "Olá")
        self.assertNotIn("provider", payload)

    async def test_invalid_text_or_language_does_not_call_provider(self):
        with patch("agents.audio_generation.agent.generate_speech", new=AsyncMock()) as speech:
            for text, language in ((" ", "pt"), ("Olá", "invalid")):
                with self.assertRaises(ValueError):
                    await text_to_speech(text, language, user_id=7)
            for tone in ("a" * 501, {"voice": "other"}):
                with self.assertRaises(ValueError):
                    await text_to_speech("Olá", user_id=7, tone=tone)
            speech.assert_not_awaited()

    async def test_dispatch_passes_scope_to_voice_cloning(self):
        from api.routes.webhook.waha.handles.chat import _dispatch_action
        module = "api.routes.webhook.waha.handles.chat"
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch(f"{module}.is_feature_blocked", new=AsyncMock(return_value=False)),
            patch(f"{module}.reserve_audio_action", new=AsyncMock(return_value=True)),
            patch(f"{module}.clone_voice", new=AsyncMock(return_value="encoded")) as speech,
            patch(f"{module}.send_audio", new=AsyncMock()) as send,
        ):
            await _dispatch_action(
                action_type="audio", action={"parameters": {"text": "Oi", "language": "pt", "voice": "other", "tone": "brincalhão"}},
                remote_id="group", user=SimpleNamespace(id=7), db=Mock(),
                db_message=SimpleNamespace(message_id="request"), scheduler=None, context={}, group_id=3,
            )
        speech.assert_awaited_once_with("Oi", "other", language="pt", user_id=7, group_id=3)
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
