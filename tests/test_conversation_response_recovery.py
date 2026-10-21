import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from api.routes.webhook.waha.handles.chat import _dispatch_gork_response


class ConversationResponseRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def _dispatch(self):
        await _dispatch_gork_response(
            raw_response="[168009]",
            remote_id="group-id",
            message_id="external-message-id",
            user=SimpleNamespace(id=7),
            db=Mock(),
            db_message=SimpleNamespace(id=99),
            scheduler=Mock(),
            context={},
            group_id=3,
            database_context="database results",
        )

    async def test_retries_malformed_model_response_once_and_dispatches_recovery(self):
        recovered = {
            "reasoning": "Recovered response.",
            "queries": [],
            "actions": [
                {"action": "message", "content": "Resposta recuperada", "language": "pt"}
            ],
        }

        with (
            patch(
                "api.routes.webhook.waha.handles.chat.conversation_agent",
                new=AsyncMock(return_value=json.dumps(recovered)),
            ) as retry,
            patch(
                "api.routes.webhook.waha.handles.chat._dispatch_action",
                new=AsyncMock(return_value=True),
            ) as dispatch_action,
            patch(
                "api.routes.webhook.waha.handles.chat.is_feature_blocked",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "api.routes.webhook.waha.handles.chat.send_message",
                new=AsyncMock(),
            ) as send_message,
            patch(
                "api.routes.webhook.waha.handles.chat.logger.error",
                new=AsyncMock(),
            ),
        ):
            await self._dispatch()

        retry.assert_awaited_once()
        retry_context = retry.await_args.kwargs["additional_context"]
        self.assertIn("database results", retry_context)
        self.assertIn("RESPONSE FORMAT RETRY", retry_context)
        dispatch_action.assert_awaited_once()
        send_message.assert_not_awaited()

    async def test_sends_fallback_after_retry_is_also_malformed(self):
        with (
            patch(
                "api.routes.webhook.waha.handles.chat.conversation_agent",
                new=AsyncMock(return_value="[168014]"),
            ) as retry,
            patch(
                "api.routes.webhook.waha.handles.chat.send_message",
                new=AsyncMock(),
            ) as send_message,
            patch(
                "api.routes.webhook.waha.handles.chat.logger.error",
                new=AsyncMock(),
            ),
        ):
            await self._dispatch()

        retry.assert_awaited_once()
        send_message.assert_awaited_once_with(
            "group-id",
            "Desculpa, tive um problema interno. Tenta de novo",
            "external-message-id",
        )

    async def test_sends_fallback_when_retry_request_fails(self):
        with (
            patch(
                "api.routes.webhook.waha.handles.chat.conversation_agent",
                new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
            ) as retry,
            patch(
                "api.routes.webhook.waha.handles.chat.send_message",
                new=AsyncMock(),
            ) as send_message,
            patch(
                "api.routes.webhook.waha.handles.chat.logger.error",
                new=AsyncMock(),
            ) as log_error,
        ):
            await self._dispatch()

        retry.assert_awaited_once()
        self.assertEqual(log_error.await_args_list[-1].args[1], "ParseRetryError")
        send_message.assert_awaited_once_with(
            "group-id",
            "Desculpa, tive um problema interno. Tenta de novo",
            "external-message-id",
        )


if __name__ == "__main__":
    unittest.main()
