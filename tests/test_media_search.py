import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from jsonschema import ValidationError
from sqlalchemy.dialects import postgresql

from services import media_search as search
from services.media_delivery import deliver_media
from services.mcp_runtime import complete_with_mcp


def media(identifier=1, kind="audio", **changes):
    return SimpleNamespace(id=identifier, type=kind, name="Bruh", description="Som de decepção e descrença.",
                           bucket="whatsapp", path="sup_media/audio/bruh.mp3", **changes)


def rows(values, scalar=False):
    result = Mock()
    result.all.return_value = values
    result.scalars.return_value = values
    result.scalar_one_or_none.return_value = values[0] if values else None
    return result


class TextSearchTests(unittest.TestCase):
    def test_accents_and_typo_within_description(self):
        self.assertEqual(search.text_similarity("decepcao", "Um som de decepção."), 1)
        self.assertGreater(search.text_similarity("brhu", "bruh"), .55)
        self.assertGreater(search.text_similarity("cachoro pulando", "vídeo de um cachorro pulando na piscina"), .8)
        self.assertLess(search.text_similarity("elefante", "bruh"), .55)
        self.assertLess(search.text_similarity("cao", "educacao"), .55)

    def test_group_scope_never_uses_private_sender(self):
        sql = str(search.conversation_scope(3, 7).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("group_id = 7", sql)
        self.assertNotIn("user_id = 3", sql)
        self.assertIn("deleted_at IS NULL", sql)

    def test_dm_scope_excludes_groups_and_other_recipients(self):
        sql = str(search.conversation_scope(3, None).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("group_id IS NULL", sql)
        self.assertIn("chat_user_id = 3", sql)
        self.assertIn("chat_user_id IS NULL", sql)


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        pending = patch.object(search, "index_pending_audio", new=AsyncMock(return_value=(0, False)))
        pending.start()
        self.addCleanup(pending.stop)

    async def test_hybrid_merges_scores_without_duplicate_ids_or_storage_paths(self):
        audio = media()
        db = SimpleNamespace(execute=AsyncMock(side_effect=[rows([audio]), rows([]), rows([(audio, .81)]), rows([])]))
        with patch.object(search, "generate_text_embeddings", new=AsyncMock(return_value=[.1] * 2560)):
            result = await search.search_media(db, {"query": "brhu", "media_type": "audio"}, user_id=3, group_id=7)
        self.assertEqual(len(result["results"]), 1)
        item = result["results"][0]
        self.assertEqual(item["media_source"], "library")
        self.assertGreater(item["text_similarity"], .55)
        self.assertEqual(item["semantic_similarity"], .81)
        self.assertNotIn("bucket", item)
        self.assertNotIn("path", item)

    async def test_missing_embedding_provider_still_finds_transcription_by_text(self):
        audio = media()
        audio.description = None
        db = SimpleNamespace(execute=AsyncMock(side_effect=[rows([]), rows([(audio, "o universo nao se importa comigo")])]))
        with patch.object(search, "generate_text_embeddings", new=AsyncMock(return_value=[])):
            result = await search.search_media(db, {"query": "universo"}, user_id=3)
        self.assertEqual(result["results"][0]["media_source"], "conversation")
        self.assertFalse(result["semantic_available"])
        for call in db.execute.call_args_list:
            sql = str(call.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            if "content.message" in sql:
                self.assertIn("group_id IS NULL", sql)

    async def test_model_cannot_override_scope_or_increase_limit(self):
        for arguments in ({"query": "x", "group_id": 99}, {"query": "x", "limit": 100}, {"query": ""}):
            with self.assertRaises(ValidationError):
                await search.search_media(Mock(), arguments, user_id=3)

    async def test_selected_attachment_is_resolved_in_scope(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=rows([])))
        self.assertIsNone(await search.resolve_media(db, user_id=3, group_id=7, message_id=42))
        sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.assertIn("group_id = 7", sql)
        self.assertIn("message.id = 42", sql)

    async def test_audio_transcript_is_indexed_for_media_and_messages(self):
        message = SimpleNamespace(id=4, media_id=5, message_id="external")
        with (
            patch.object(search, "generate_text_embeddings", new=AsyncMock(return_value=[.2] * 2560)),
            patch.object(search, "MediaRepository") as media_repo,
            patch.object(search, "MessageRepository") as message_repo,
        ):
            media_repo.return_value.update = AsyncMock()
            message_repo.return_value.update = AsyncMock()
            await search.index_audio_transcript(Mock(), 3, message, "bruh")
            self.assertEqual(media_repo.return_value.update.call_args.args[1]["description"], "bruh")
            self.assertEqual(len(message_repo.return_value.update.call_args.args[1]["content_embedding"]), 2560)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_correct_sender_for_each_kind(self):
        for kind in ("audio", "image", "video"):
            with (
                self.subTest(kind=kind),
                patch("services.media_delivery.resolve_media", new=AsyncMock(return_value=media(kind=kind))),
                patch("services.media_delivery.S3Client") as storage,
                patch("services.media_delivery.send_audio", new=AsyncMock()) as audio,
                patch("services.media_delivery.send_image", new=AsyncMock()) as image,
                patch("services.media_delivery.send_video", new=AsyncMock()) as video,
            ):
                storage.return_value.connect = AsyncMock()
                storage.return_value.get_image_base64 = AsyncMock(return_value="base64")
                await deliver_media(Mock(), remote_id="group@g.us", user_id=3, group_id=7,
                                    action_type=f"send_{kind}", parameters={"media_id": 1, "media_source": "conversation"})
                self.assertEqual((audio.await_count, image.await_count, video.await_count),
                                 tuple(int(value == kind) for value in ("audio", "image", "video")))

    async def test_missing_or_wrong_type_never_downloads(self):
        for selected in (None, media(kind="video")):
            with patch("services.media_delivery.resolve_media", new=AsyncMock(return_value=selected)), patch("services.media_delivery.S3Client") as storage:
                with self.assertRaises(ValueError):
                    await deliver_media(Mock(), remote_id="user", user_id=3, group_id=None,
                                        action_type="send_audio", parameters={"media_id": 1})
                storage.assert_not_called()


class AudioBackfillTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_transcripts_indexed_in_a_single_batch(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=rows([(1, 11, "bruh"), (2, 12, "get out")])))
        with (
            patch.object(search, "ModelRepository") as models,
            patch.object(search, "MediaRepository") as media_repo,
            patch.object(search, "MessageRepository") as message_repo,
            patch.object(search, "InteractionRepository") as interactions,
            patch.object(search, "request_embeddings", new=AsyncMock(return_value={"data": [
                {"index": 1, "embedding": [.2] * 2560}, {"index": 0, "embedding": [.1] * 2560},
            ], "usage": {"prompt_tokens": 5}})) as provider,
        ):
            models.return_value.get_default_embedding_model = AsyncMock(return_value=SimpleNamespace(id=4, openrouter_id="embedding-model"))
            media_repo.return_value.update = AsyncMock()
            message_repo.return_value.update = AsyncMock()
            interactions.return_value.create_interaction = AsyncMock()
            self.assertEqual(await search.index_pending_audio(db, 3, 7), (2, False))
            provider.assert_awaited_once_with(["bruh", "get out"], "embedding-model")
            self.assertEqual(media_repo.return_value.update.call_args_list[0].args[1]["description_embedding"][0], .1)
            sql = str(db.execute.call_args.args[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            self.assertIn("group_id = 7", sql)
            self.assertIn("description_embedding IS NULL", sql)


class NativeToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_result_is_given_to_model_before_send_action(self):
        seen = []
        responses = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "search-1", "type": "function", "function": {"name": "search_media", "arguments": '{"query":"brhu","media_type":"audio"}'}}
            ]}}]},
            {"choices": [{"message": {"role": "assistant", "content": json.dumps({"reasoning": "found", "queries": [], "actions": [
                {"action": "send_audio", "parameters": {"media_id": 1, "media_source": "library"}}
            ]})}}]},
        ]
        async def complete(payload):
            seen.append(deepcopy(payload))
            return responses.pop(0)
        with (
            patch("services.mcp_runtime.available_bindings", new=AsyncMock(return_value=({}, []))),
            patch("services.mcp_runtime.search_media", new=AsyncMock(return_value={"results": [{"media_id": 1, "media_source": "library", "type": "audio"}]})) as tool,
        ):
            result = await complete_with_mcp({"messages": []}, Mock(), user_id=3, group_id=7, message_id=9,
                                             completion=complete, record_response=AsyncMock())
        self.assertEqual(tool.call_args.kwargs, {"user_id": 3, "group_id": 7})
        self.assertEqual(seen[1]["messages"][-1]["role"], "tool")
        self.assertEqual(json.loads(result["choices"][0]["message"]["content"])["actions"][0]["action"], "send_audio")
