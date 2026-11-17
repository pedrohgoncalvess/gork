import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx

from api.routes.webhook.waha.handles.core import get_explicit_command_feature, has_explicit_command
from api.routes.webhook.waha.handles.trapo import handle_trapo_command
from api.routes.webhook.waha.processors.common import process_commands
from external.trapo import TrapoError, generate_trapo


MODULE = "api.routes.webhook.waha.handles.trapo"
PNG = b"\x89PNG fake"


def mock_client(handler):
    real = httpx.AsyncClient
    return patch("external.trapo.httpx.AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


class TrapoClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_raw_command_and_returns_png(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

        with mock_client(handler):
            image = await generate_trapo("@123 !trapo eh os guri :time=gremio")

        self.assertEqual(image, PNG)
        self.assertEqual(requests, [{"cmd": "@123 !trapo eh os guri :time=gremio"}])

    async def test_explicit_phrase_is_sent_along_with_command(self):
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, content=PNG)

        with mock_client(handler):
            await generate_trapo("!trapo :inter", "frase citada")

        self.assertEqual(requests, [{"cmd": "!trapo :inter", "frase": "frase citada"}])

    async def test_validation_error_becomes_trapo_error(self):
        with mock_client(lambda request: httpx.Response(400, json={"error": "Faltou a frase."})):
            with self.assertRaisesRegex(TrapoError, "Faltou a frase."):
                await generate_trapo("!trapo")


class TrapoHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = SimpleNamespace(message_id="request", quoted_message_id=None, content="!trapo eh os guri")

    def test_command_is_recognized(self):
        self.assertTrue(has_explicit_command("@123 !trapo eh os guri :time=gremio"))
        self.assertEqual(get_explicit_command_feature("!trapo eh os guri"), "trapo")

    async def test_sends_generated_image_as_png(self):
        with (
            patch(f"{MODULE}.generate_trapo", new=AsyncMock(return_value=PNG)) as generate,
            patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
        ):
            await handle_trapo_command("chat", "request", "!trapo eh os guri :gremio", self.message, Mock())

        generate.assert_awaited_once_with("!trapo eh os guri :gremio", None)
        self.assertEqual(send.await_args.args, ("chat", base64.b64encode(PNG).decode()))
        self.assertEqual(send.await_args.kwargs["mimetype"], "image/png")

    async def test_uses_quoted_message_when_command_has_no_phrase(self):
        self.message.quoted_message_id = 7
        repository = Mock(find_by_id=AsyncMock(return_value=SimpleNamespace(content=" vendi o carro pra ver o jogo ")))
        with (
            patch("database.operations.content.MessageRepository", return_value=repository),
            patch(f"{MODULE}.generate_trapo", new=AsyncMock(return_value=PNG)) as generate,
            patch(f"{MODULE}.send_image", new=AsyncMock()),
        ):
            await handle_trapo_command("chat", "request", "!trapo :inter", self.message, Mock())

        repository.find_by_id.assert_awaited_once_with(7)
        generate.assert_awaited_once_with("!trapo :inter", "vendi o carro pra ver o jogo")

    async def test_api_validation_message_is_sent_to_chat(self):
        with (
            patch(f"{MODULE}.generate_trapo", new=AsyncMock(side_effect=TrapoError("Faltou a frase."))),
            patch(f"{MODULE}.send_image", new=AsyncMock()) as image,
            patch(f"{MODULE}.send_message", new=AsyncMock()) as message,
        ):
            await handle_trapo_command("chat", "request", "!trapo", self.message, Mock())

        image.assert_not_awaited()
        message.assert_awaited_once_with("chat", "🏳️ Faltou a frase.", "request")

    async def test_unexpected_failure_sends_generic_message(self):
        with (
            patch(f"{MODULE}.generate_trapo", new=AsyncMock(side_effect=httpx.ConnectError("down"))),
            patch(f"{MODULE}.logger.error", new=AsyncMock()),
            patch(f"{MODULE}.send_message", new=AsyncMock()) as message,
        ):
            await handle_trapo_command("chat", "request", "!trapo eh os guri", self.message, Mock())

        self.assertIn("Não consegui gerar o trapo", message.await_args.args[1])

    async def test_dispatch_routes_command_and_checks_disabled_rule(self):
        module = "api.routes.webhook.waha.processors.common"
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)) as rule,
            patch(f"{module}.handle_trapo_command", new=AsyncMock()) as handler,
        ):
            db = Mock()
            await process_commands("!trapo eh os guri", "chat", "request", SimpleNamespace(id=1), {}, None, db, Mock(), {}, self.message)

        self.assertEqual(rule.await_args.kwargs["command"], "trapo")
        handler.assert_awaited_once_with(
            remote_id="chat", message_id="request", conversation="!trapo eh os guri", db_message=self.message, db=db,
        )


if __name__ == "__main__":
    unittest.main()
