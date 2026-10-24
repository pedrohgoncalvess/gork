import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents.transcriber.agent import transcribe_audio
from agents.transcriber.parser import audio_format


class AudioContainerTests(unittest.TestCase):
    def test_detects_original_containers_without_transcoding(self):
        for content, expected in (
            (b"OggSopus-data", "ogg"), (b"RIFF0000WAVEdata", "wav"),
            (b"ID3mp3-data", "mp3"), (b"fLaCdata", "flac"),
            (b"0000ftypM4A ", "m4a"), (b"\xff\xf1aac", "aac"),
        ):
            with self.subTest(format=expected):
                self.assertEqual(audio_format(content, "wrong.wav"), expected)

    def test_empty_or_unknown_audio_fails_before_provider_request(self):
        for content in (b"", b"unknown-data"):
            with self.assertRaises(ValueError):
                audio_format(content)


class TranscriptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_ogg_and_quote_reach_openrouter_with_scoped_model(self):
        module = "agents.transcriber.agent"
        original = base64.b64encode(b"OggSoriginal-voice-note").decode()
        agent = SimpleNamespace(id=2, prompt="Transcribe faithfully.", response_format='{"type":"json_object"}')
        model = SimpleNamespace(id=3, openrouter_id="test/audio-input")
        response = {"choices": [{"message": {"content": '{"transcription":"Hello"}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
        with (
            patch(f"{module}.PgConnection", return_value=AsyncMock()),
            patch(f"{module}.AgentRepository") as agents,
            patch(f"{module}.ModelConversationRepository") as models,
            patch(f"{module}.InteractionRepository") as interactions,
            patch(f"{module}.CommandRepository") as commands,
            patch(f"{module}.download_media", new=AsyncMock(return_value=(original, "voice.opus"))) as download,
            patch(f"{module}.completions", new=AsyncMock(return_value=response)) as complete,
        ):
            agents.return_value.find_by_name = AsyncMock(return_value=agent)
            models.return_value.resolve_agent_model = AsyncMock(return_value=model)
            interactions.return_value.create_interaction = AsyncMock()
            commands.return_value.create_command = AsyncMock(return_value=SimpleNamespace(id=4))
            for direct in (True, False):
                body = {"data": {"key": {"id": "current"}, "message": {"audioMessage": {"mimetype": "audio/ogg"}} if direct else {},
                                 "contextInfo": {"stanzaId": "quoted"}}}
                self.assertEqual(await transcribe_audio(body, 7, 9, command=True), "Hello")
                download.assert_awaited_with("current" if direct else "quoted")
                payload = complete.await_args.args[0]
                self.assertEqual(payload["messages"][0]["content"][1]["input_audio"], {"data": original, "format": "ogg"})
                models.return_value.resolve_agent_model.assert_awaited_with(agent, user_id=7, group_id=9)
                self.assertEqual(interactions.return_value.create_interaction.await_args.kwargs["response"], "Hello")
                commands.return_value.create_command.assert_awaited_with("transcribe", 7, group_id=9)
            self.assertEqual(commands.return_value.create_command.await_count, 2)
