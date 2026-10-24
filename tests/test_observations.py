import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.dialects import postgresql

from llm_access.observations import save_observation, search_observations


def _note(note_id, content="O relógio suíço é uma piada sobre atrasos", indexed=True):
    return SimpleNamespace(
        id=note_id, content=content, source_message_id=99,
        embedding_model_id=7 if indexed else None, embedding=None,
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )


class _Result:
    def __init__(self, notes=()):
        self.notes = list(notes)

    def scalar_one_or_none(self):
        return self.notes[0] if self.notes else None

    def scalar_one(self):
        return self.notes[0]

    def scalars(self):
        return self

    def all(self):
        return self.notes


class _Session:
    def __init__(self, *results):
        self.results = iter(results)
        self.statements = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, statement):
        self.statements.append(statement)
        return next(self.results)


def _sql(statement):
    return str(statement.compile(dialect=postgresql.dialect()))


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_save_uses_group_scope_and_server_source(self):
        session = _Session(_Result(), _Result([_note(1)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=([1.0] * 2560, 7))):
            result = await save_observation(session, 30, 10, "  piada interna  ", 99)
        values = session.statements[1].compile().params
        self.assertEqual(values["group_id"], 30)
        self.assertIsNone(values["user_id"])
        self.assertEqual(values["source_message_id"], 99)
        self.assertEqual(values["content"], "piada interna")
        self.assertEqual(values["embedding_model_id"], 7)
        self.assertTrue(result["embedding_indexed"])
        self.assertIn("ON CONFLICT DO NOTHING", _sql(session.statements[1]))
        session.commit.assert_awaited_once()

    async def test_dm_save_survives_unavailable_embeddings(self):
        session = _Session(_Result(), _Result([_note(1, indexed=False)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=(None, None))):
            result = await save_observation(session, None, 10, "piada interna", 99)
        values = session.statements[1].compile().params
        self.assertIsNone(values["group_id"])
        self.assertEqual(values["user_id"], 10)
        self.assertIsNone(values["embedding"])
        self.assertFalse(result["embedding_indexed"])
        self.assertIn("group_id IS NULL", _sql(session.statements[0]))
        self.assertIn("user_id =", _sql(session.statements[0]))

    async def test_duplicate_does_not_generate_embedding_or_insert(self):
        session = _Session(_Result([_note(1, content="literal 100%_piada"), _note(2, content="100 outra piada")]))
        with patch("llm_access.observations._embedding", new=AsyncMock()) as embed:
            result = await save_observation(session, 30, 10, "piada interna")
        self.assertTrue(result["already_saved"])
        embed.assert_not_awaited()
        self.assertEqual(len(session.statements), 1)

    async def test_unindexed_duplicate_can_be_indexed_later(self):
        note = _note(1, indexed=False)
        session = _Session(_Result([note]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=([1.0] * 2560, 7))):
            result = await save_observation(session, 30, 10, note.content)
        self.assertTrue(result["already_saved"])
        self.assertTrue(result["embedding_indexed"])
        session.refresh.assert_awaited_once_with(note)

    async def test_concurrent_duplicate_returns_the_existing_scoped_note(self):
        session = _Session(_Result(), _Result(), _Result([_note(5)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=(None, None))):
            result = await save_observation(session, 30, 10, "piada interna")
        self.assertEqual(result["id"], 5)
        self.assertIn("observation.group_id =", _sql(session.statements[2]))

    async def test_recent_dm_notes_are_scoped_and_limited(self):
        session = _Session(_Result([_note(1)]))
        result = await search_observations(session, None, 10, limit=999)
        sql = _sql(session.statements[0])
        self.assertIn("group_id IS NULL", sql)
        self.assertIn("user_id =", sql)
        self.assertEqual(session.statements[0].compile().params["param_1"], 50)
        self.assertEqual(result["mode"], "recent")

    async def test_term_search_is_bound_and_escapes_wildcards(self):
        session = _Session(_Result([_note(1, content="literal 100%_piada"), _note(2, content="100 outra piada")]))
        with patch("llm_access.observations._embedding", new=AsyncMock()) as embed:
            result = await search_observations(session, 30, 10, "100%_piada", mode="term")
        stmt = session.statements[0]
        self.assertNotIn("search_document", _sql(stmt))
        self.assertIn("observation.group_id =", _sql(stmt))
        self.assertNotIn("100%_piada", stmt.compile().params.values())
        self.assertEqual([n["id"] for n in result["observations"]], [1])
        embed.assert_not_awaited()

    async def test_hybrid_fuses_rankings_and_deduplicates_notes(self):
        session = _Session(_Result([_note(1), _note(2)]), _Result([_note(2), _note(3)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=([1.0] * 2560, 7))):
            result = await search_observations(session, 30, 10, "relógio suíço")
        self.assertEqual([n["id"] for n in result["observations"]], [2, 1, 3])
        sql = _sql(session.statements[1])
        self.assertIn("HALFVEC(2560)", sql)
        self.assertIn("<=>", sql)
        self.assertIn("observation.group_id =", sql)
        self.assertIn("embedding_model_id =", sql)
        self.assertTrue(result["semantic_available"])

    async def test_hybrid_falls_back_to_terms_when_embeddings_fail(self):
        session = _Session(_Result([_note(1, indexed=False)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=(None, None))):
            result = await search_observations(session, 30, 10, "relógio")
        self.assertFalse(result["semantic_available"])
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(len(session.statements), 1)

    async def test_similarity_only_does_not_return_text_matches_on_failure(self):
        session = _Session()
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=(None, None))):
            result = await search_observations(session, None, 10, "piada", mode="similarity")
        self.assertFalse(result["semantic_available"])
        self.assertEqual(result["observations"], [])

    async def test_dm_similarity_search_is_scoped_to_current_user(self):
        session = _Session(_Result([_note(1)]))
        with patch("llm_access.observations._embedding", new=AsyncMock(return_value=([1.0] * 2560, 7))):
            result = await search_observations(session, None, 10, "piada", mode="similarity")
        sql = _sql(session.statements[0])
        self.assertIn("group_id IS NULL", sql)
        self.assertIn("user_id =", sql)
        self.assertIn("embedding_model_id =", sql)
        self.assertEqual([n["id"] for n in result["observations"]], [1])

    async def test_embedding_uses_same_model_for_generation_and_index(self):
        from llm_access.observations import _embedding
        model = SimpleNamespace(id=7)
        with (
            patch("llm_access.observations.ModelRepository") as repo,
            patch("llm_access.observations.generate_text_embeddings", new=AsyncMock(return_value=[1.0] * 2560)) as generate,
        ):
            repo.return_value.get_default_embedding_model = AsyncMock(return_value=model)
            vector, model_id = await _embedding("session", "piada", 10, 30)
        self.assertEqual(model_id, 7)
        self.assertEqual(len(vector), 2560)
        generate.assert_awaited_once_with(
            "piada", db="session", user_id=10, group_id=30, embedding_model=model,
        )

    async def test_invalid_content_and_mode_are_rejected(self):
        for content in (None, " ", "x" * 4001):
            with self.subTest(content_type=type(content)):
                with self.assertRaises(ValueError):
                    await save_observation(_Session(), 30, 10, content)
        with self.assertRaises(ValueError):
            await search_observations(_Session(), 30, 10, "piada", mode="invalid")


class ObservationToolScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_calls_ignore_model_supplied_scope_and_source(self):
        from api.routes.webhook.waha.handles.chat import _execute_database_query
        for group_id in (None, 30):
            with self.subTest(group_id=group_id):
                with patch("api.routes.webhook.waha.handles.chat.save_observation", new=AsyncMock(return_value={"id": 1})) as save:
                    result = await _execute_database_query(
                        db="session", group_id=group_id, user_id=10,
                        query={"query_type": "save_observation", "parameters": {
                            "content": "piada interna", "group_id": 999,
                            "user_id": 999, "source_message_id": 999,
                        }}, source_message_id=99,
                    )
                save.assert_awaited_once_with(
                    db="session", group_id=group_id, user_id=10,
                    content="piada interna", source_message_id=99,
                )
                self.assertEqual(result["result"], {"id": 1})
                with patch("api.routes.webhook.waha.handles.chat.search_observations", new=AsyncMock(return_value={"observations": []})) as search:
                    await _execute_database_query(
                        db="session", group_id=group_id, user_id=10,
                        query={"query_type": "search_observations", "parameters": {
                            "query": "piada", "group_id": 999, "user_id": 999,
                        }},
                    )
                search.assert_awaited_once_with(
                    db="session", group_id=group_id, user_id=10,
                    query="piada", mode="hybrid", limit=None,
                )
