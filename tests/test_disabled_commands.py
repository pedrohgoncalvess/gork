import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.routes.webhook.evolution.processors.common import process_commands
from database.operations.manager.disabled_command import (
    DisabledCommandRepository,
    normalize_command,
)
from services.disabled_commands import get_disabled_command_message


class DisabledCommandNormalizationTests(unittest.TestCase):
    def test_commands_and_agent_action_aliases_share_the_same_feature(self):
        self.assertEqual(normalize_command("!IMAGE"), "image")
        self.assertEqual(normalize_command("send_image"), "image")
        self.assertEqual(normalize_command("generate_sticker"), "sticker")
        self.assertEqual(normalize_command("consumption"), "usage")
        self.assertEqual(normalize_command("message"), "interaction")
        self.assertEqual(normalize_command("!list"), "favorite")


class DisabledCommandRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_most_specific_active_rule_from_query(self):
        expected = SimpleNamespace(message="Indisponível para você neste grupo.")
        result = Mock()
        result.scalar_one_or_none.return_value = expected
        db = Mock()
        db.execute = AsyncMock(return_value=result)

        found = await DisabledCommandRepository(db).find_active(
            command="!video",
            user_id=12,
            group_id=34,
        )

        self.assertIs(found, expected)
        statement = db.execute.await_args.args[0]
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("disabled_command.user_id = 12", sql)
        self.assertIn("disabled_command.group_id = 34", sql)
        self.assertIn("disabled_command.disabled_until", sql)
        self.assertIn("ORDER BY", sql)

    async def test_service_returns_custom_message(self):
        rule = SimpleNamespace(message="Vídeos em manutenção.")
        with patch(
            "services.disabled_commands.DisabledCommandRepository.find_active",
            new=AsyncMock(return_value=rule),
        ):
            message = await get_disabled_command_message(Mock(), "video", 1, 2)

        self.assertEqual(message, "Vídeos em manutenção.")


class DisabledCommandDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_command_is_stopped_before_handler(self):
        user = SimpleNamespace(id=7)
        with (
            patch(
                "api.routes.webhook.evolution.processors.common.get_disabled_command_message",
                new=AsyncMock(return_value="Comando temporariamente desativado."),
            ),
            patch(
                "api.routes.webhook.evolution.processors.common.send_message",
                new=AsyncMock(),
            ) as send,
            patch(
                "api.routes.webhook.evolution.processors.common.process_explicit_commands",
                new=AsyncMock(),
            ) as dispatch,
        ):
            await process_commands(
                "!sticker teste",
                "remote",
                "message-id",
                user,
                {},
                4,
                Mock(),
                Mock(),
                {},
                Mock(),
            )

        send.assert_awaited_once_with(
            "remote", "Comando temporariamente desativado.", "message-id"
        )
        dispatch.assert_not_awaited()

    async def test_generic_interaction_can_be_disabled_too(self):
        user = SimpleNamespace(id=7)
        with (
            patch(
                "api.routes.webhook.evolution.processors.common.get_disabled_command_message",
                new=AsyncMock(return_value="Interações pausadas."),
            ) as lookup,
            patch(
                "api.routes.webhook.evolution.processors.common.send_message",
                new=AsyncMock(),
            ),
            patch(
                "api.routes.webhook.evolution.processors.common.handle_conversation_agent",
                new=AsyncMock(),
            ) as conversation,
        ):
            await process_commands(
                "@Gork oi",
                "remote",
                "message-id",
                user,
                {},
                None,
                Mock(),
                Mock(),
                {},
                Mock(),
            )

        self.assertEqual(lookup.await_args.kwargs["command"], "interaction")
        conversation.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
