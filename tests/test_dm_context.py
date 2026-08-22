import unittest
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from agents.execution.conversation import (
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
