import unittest
from unittest.mock import AsyncMock, patch

from api.routes.webhook.evolution.handles.utility import handle_help_command


class HelpCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_help_includes_video_command_and_sends_response(self):
        with patch(
            "api.routes.webhook.evolution.handles.utility.send_message",
            new=AsyncMock(),
        ) as send:
            await handle_help_command("remote", "message-id")

        send.assert_awaited_once()
        remote_id, help_message, message_id = send.await_args.args
        self.assertEqual(remote_id, "remote")
        self.assertEqual(message_id, "message-id")
        self.assertIn("🎬 *VÍDEOS*", help_message)
        self.assertIn("*!video*", help_message)


if __name__ == "__main__":
    unittest.main()
