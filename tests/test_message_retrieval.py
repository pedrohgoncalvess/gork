import unittest

from sqlalchemy.dialects import postgresql

from database.models.manager import Remember  # Register group/user relationships.

from llm_access.database import (
    DEFAULT_MESSAGE_LIMIT,
    MAX_MESSAGE_LIMIT,
    _message_limit,
    get_conversation_messages,
    get_group_messages,
    get_user_messages,
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
    def test_message_limit_defaults_to_200_and_caps_at_2000(self):
        self.assertEqual(200, DEFAULT_MESSAGE_LIMIT)
        self.assertEqual(DEFAULT_MESSAGE_LIMIT, _message_limit(None))
        self.assertEqual(1, _message_limit(0))
        self.assertEqual(250, _message_limit(250))
        self.assertEqual(1_000, _message_limit(1_000))
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
        self.assertIn("LIMIT 2000", sql)

    async def test_group_and_user_retrieval_support_default_and_larger_limits(self):
        for retrieve, extra_params in (
            (get_group_messages, {}),
            (get_user_messages, {"user_id": 10}),
        ):
            for limit, expected in ((None, 200), (1_000, 1_000), (5_000, 2_000)):
                with self.subTest(query=retrieve.__name__, limit=limit):
                    session = _CapturingSession()
                    await retrieve(db=session, group_id=30, limit=limit, **extra_params)
                    sql = str(session.statement.compile(
                        dialect=postgresql.dialect(),
                        compile_kwargs={"literal_binds": True},
                    ))
                    self.assertIn(f"LIMIT {expected}", sql)
                    self.assertIn("group_id = 30", sql)
                    self.assertIn("deleted_at IS NULL", sql)
                    if extra_params:
                        self.assertIn("message.user_id = 10", sql)


if __name__ == "__main__":
    unittest.main()
