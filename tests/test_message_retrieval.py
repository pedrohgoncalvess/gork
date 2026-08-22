import unittest

from sqlalchemy.dialects import postgresql

from llm_access.database import (
    DEFAULT_LIMIT,
    MAX_MESSAGE_LIMIT,
    _message_limit,
    get_conversation_messages,
)


class _EmptyResult:
    def all(self):
        return []


class _CapturingSession:
    statement = None

    async def execute(self, statement):
        self.statement = statement
        return _EmptyResult()


class MessageRetrievalTests(unittest.IsolatedAsyncioTestCase):
    def test_message_limit_defaults_to_50_and_caps_at_500(self):
        self.assertEqual(DEFAULT_LIMIT, _message_limit(None))
        self.assertEqual(1, _message_limit(0))
        self.assertEqual(250, _message_limit(250))
        self.assertEqual(MAX_MESSAGE_LIMIT, _message_limit(5_000))

    async def test_private_retrieval_is_scoped_and_capped(self):
        session = _CapturingSession()

        result = await get_conversation_messages(
            db=session,
            user_id=10,
            gork_user_id=20,
            limit=5_000,
        )

        sql = str(session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        self.assertEqual([], result)
        self.assertIn("group_id IS NULL", sql)
        self.assertIn("user_id IN (10, 20)", sql)
        self.assertIn("LIMIT 500", sql)


if __name__ == "__main__":
    unittest.main()
