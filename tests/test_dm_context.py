import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy.dialects import postgresql

from agents.execution.conversation import (
    _build_group_request_messages,
    _load_group_reply_chain,
    _format_direct_message_content,
    _format_group_message_content,
)
from api.routes.webhook.evolution.handles.chat import _sent_message_id
from database.operations.content.message import MessageRepository


class _EmptyResult:
    def unique(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingSession:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyResult()


class DirectMessageContextTests(unittest.IsolatedAsyncioTestCase):
    def _group_message(self, message_id, sender_name, user_id, content, quoted_id=None, group_id=1):
        return SimpleNamespace(
            id=message_id, sender=SimpleNamespace(name=sender_name),
            user_id=user_id, content=content, quoted_message_id=quoted_id,
            group_id=group_id, media_id=None,
            created_at=datetime(2026, 9, 30, 17, 53),
        )

    async def test_pedro_current_turn_prioritizes_own_reply_chain_over_marcus_interview(self):
        marcus = self._group_message(177009, "Marcus", 2, "Caguei mole agr é fazer entrevista")
        murillo = self._group_message(177012, "Murillo Nahas", 3, "vtncccc")
        gork = self._group_message(177014, "Gork", 9, "Vtn tbm kkkk", 177012)
        pedro = self._group_message(177018, "Pedro Henrique Gonçalves", 1, "vtn tbm kkkk", 177014)
        lookup = {message.id: message for message in (marcus, murillo, gork, pedro)}
        chain = await _load_group_reply_chain(pedro, lookup, SimpleNamespace(find_by_id=AsyncMock()))
        messages = _build_group_request_messages(
            "prompt", pedro, [marcus, murillo, gork], chain, lookup, {}, {}, 9,
        )
        current = json.loads(messages[-1]["content"])
        self.assertEqual(current["context_type"], "CURRENT_MESSAGE")
        self.assertEqual(current["current_message_id"], 177018)
        self.assertEqual(current["current_sender_name"], "Pedro Henrique Gonçalves")
        self.assertEqual([entry["role"] for entry in current["reply_chain"]], ["user", "assistant"])
        self.assertNotIn("Marcus", json.dumps(current))
        self.assertIn("sender=Marcus", messages[2]["content"])
        self.assertEqual(len(messages), 4)  # chain appears once, inside the current envelope

    async def test_marcus_reply_does_not_inherit_jose_name_from_parallel_topic(self):
        jose = self._group_message(177034, "José Thomaz", 4, "Vc simpatiza com negros?")
        gork = self._group_message(177020, "Gork", 9, "Boa sorte aí, Marcus! Vai dar certo!")
        marcus = self._group_message(177035, "Marcus", 2, "Vlw gork. Tudo de bom pra ti", 177020)
        lookup = {message.id: message for message in (jose, gork, marcus)}
        chain = await _load_group_reply_chain(marcus, lookup, SimpleNamespace(find_by_id=AsyncMock()))
        messages = _build_group_request_messages("prompt", marcus, [gork, jose], chain, lookup, {}, {}, 9)
        current = json.loads(messages[-1]["content"])
        self.assertEqual(current["current_sender_name"], "Marcus")
        self.assertNotIn("José Thomaz", json.dumps(current))

    async def test_reply_chain_loads_old_ancestors_and_stops_at_cycle_or_other_group(self):
        current = self._group_message(30, "Pedro", 1, "continua", 20)
        parent = self._group_message(20, "Gork", 9, "resposta", 10)
        ancestor = self._group_message(10, "Pedro", 1, "pergunta", 20)
        repo = SimpleNamespace(find_by_id=AsyncMock(return_value=ancestor))
        lookup = {20: parent}
        chain = await _load_group_reply_chain(current, lookup, repo)
        self.assertEqual([message.id for message in chain], [10, 20])
        repo.find_by_id.assert_awaited_once_with(10)
        ancestor.group_id = 2
        chain = await _load_group_reply_chain(current, {20: parent}, repo)
        self.assertEqual([message.id for message in chain], [20])

    async def test_private_history_is_scoped_to_dm_and_both_participants(self):
        session = _CapturingSession()
        repository = MessageRepository(session)
        until = SimpleNamespace(id=99, created_at=datetime(2026, 8, 16, 12, 30))

        await repository.find_private_conversation(
            user_id=10,
            gork_user_id=20,
            until=until,
        )

        sql = str(session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        self.assertIn("group_id IS NULL", sql)
        self.assertIn("user_id IN (10, 20)", sql)
        self.assertIn("id <= 99", sql)

    async def test_group_history_is_scoped_and_cut_off_at_current_message(self):
        session = _CapturingSession()
        repository = MessageRepository(session)
        until = SimpleNamespace(id=150, created_at=datetime(2026, 8, 16, 12, 45))

        await repository.find_by_group(group_id=7, limit=80, until=until)

        sql = str(session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        self.assertIn("group_id = 7", sql)
        self.assertIn("id <= 150", sql)
        self.assertIn("ORDER BY content.message.created_at DESC, content.message.id DESC", sql)

    def test_dm_turn_keeps_message_metadata_and_content(self):
        message = SimpleNamespace(
            id=42,
            content="continua a explicação",
            media_id=None,
            quoted_message_id=None,
            created_at=datetime(2026, 8, 16, 12, 30),
        )

        formatted = _format_direct_message_content(message, {})

        self.assertIn("message_id=42", formatted)
        self.assertIn("continua a explicação", formatted)

    def test_sent_message_id_supports_evolution_response_shapes(self):
        self.assertEqual("abc", _sent_message_id({"key": {"id": "abc"}}))
        self.assertEqual("def", _sent_message_id({"data": {"key": {"id": "def"}}}))
        self.assertIsNone(_sent_message_id({"error": "send failed"}))

    def test_group_turn_preserves_sender_reply_and_media_description(self):
        quoted = SimpleNamespace(
            id=41,
            content="olha isso",
            media_id=None,
            sender=SimpleNamespace(name="Ana"),
        )
        message = SimpleNamespace(
            id=42,
            user_id=10,
            content=None,
            media_id=5,
            quoted_message_id=41,
            created_at=datetime(2026, 8, 16, 12, 30),
            sender=SimpleNamespace(name="Pedro"),
        )
        media = SimpleNamespace(
            id=5,
            type="image",
            description="um gráfico com crescimento trimestral",
        )

        formatted = _format_group_message_content(
            message,
            {41: quoted, 42: message},
            {5: media},
            {},
        )

        self.assertIn("sender=Pedro", formatted)
        self.assertIn("sender=Ana", formatted)
        self.assertIn("Media: image", formatted)
        self.assertIn("crescimento trimestral", formatted)


if __name__ == "__main__":
    unittest.main()
