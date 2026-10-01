import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.message_context import get_mentions_from_content, verifiy_media
from services.outgoing_mentions import resolve_outgoing_mentions
from external.evolution.message import send_message


class MentionResolutionTests(unittest.IsolatedAsyncioTestCase):
    def test_outgoing_names_and_phone_resolve_to_lid_without_duplicate_notifications(self):
        users = [
            SimpleNamespace(name="andre", src_id="178709680111833", phone_number="554184538621"),
            SimpleNamespace(name="Pedro Henrique Gonçalves", src_id="161323350499368@lid", phone_number="554899865556"),
        ]
        text, mentioned = resolve_outgoing_mentions(
            "@Andre, fala com @Pedro Henrique! @554184538621 e @178709680111833@lid", users,
        )
        self.assertEqual(text, "@178709680111833, fala com @161323350499368! @178709680111833 e @178709680111833")
        self.assertEqual(mentioned, ["178709680111833@lid", "161323350499368@lid"])

    def test_ambiguous_or_unknown_names_and_emails_are_not_tagged(self):
        users = [
            SimpleNamespace(name="Pedro Silva", src_id="11111111111", phone_number=None),
            SimpleNamespace(name="Pedro Souza", src_id="22222222222", phone_number=None),
        ]
        text, mentioned = resolve_outgoing_mentions(
            "@Pedro, @desconhecido, email@Pedro e @Pedro Silva.", users,
        )
        self.assertEqual(text, "@Pedro, @desconhecido, email@Pedro e @11111111111.")
        self.assertEqual(mentioned, ["11111111111@lid"])

    def test_phone_only_identity_uses_phone_jid(self):
        user = SimpleNamespace(name="Ana", src_id="5511999999999", phone_number="5511999999999")
        self.assertEqual(
            resolve_outgoing_mentions("@Ana!", [user]),
            ("@5511999999999!", ["5511999999999@s.whatsapp.net"]),
        )

    async def test_evolution_send_contains_mentions_and_preserves_quote(self):
        client = AsyncMock()
        response = Mock()
        response.json.return_value = {"key": {"id": "sent-id"}}
        client.post.return_value = response
        with patch("external.evolution.message.httpx.AsyncClient") as factory:
            factory.return_value.__aenter__ = AsyncMock(return_value=client)
            factory.return_value.__aexit__ = AsyncMock(return_value=False)
            await send_message(
                "group@g.us", "Olá @11111111111", "quote-id", simulate_typing=False,
                mentioned=["11111111111@lid", "11111111111@lid"],
            )
        payload = client.post.await_args.kwargs["json"]
        self.assertEqual(payload["text"], "Olá @11111111111")
        self.assertEqual(payload["mentioned"], ["11111111111@lid"])
        self.assertEqual(payload["quoted"]["key"]["id"], "quote-id")

    async def test_agent_dispatch_resolves_group_mentions_before_sending_and_persisting(self):
        from api.routes.webhook.evolution.handles.chat import _dispatch_action

        andre = SimpleNamespace(name="andre", src_id="178709680111833", phone_number="554184538621")
        message = SimpleNamespace(id=99, message_id="request-id")
        with (
            patch("api.routes.webhook.evolution.handles.chat.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch("api.routes.webhook.evolution.handles.chat.is_feature_blocked", new=AsyncMock(return_value=False)),
            patch("api.routes.webhook.evolution.handles.chat.UserRepository") as users,
            patch("api.routes.webhook.evolution.handles.chat.send_message", new=AsyncMock()) as send,
            patch("api.routes.webhook.evolution.handles.chat._persist_sent_text_response", new=AsyncMock()) as persist,
        ):
            users.return_value.find_users_by_group_id = AsyncMock(return_value=[andre])
            await _dispatch_action(
                "message", {"content": "@andre, beleza?"}, "group@g.us",
                SimpleNamespace(id=1), Mock(), message, Mock(), {}, 7,
            )
        send.assert_awaited_once_with(
            "group@g.us", "@178709680111833, beleza?", "request-id", True,
            mentioned=["178709680111833@lid"],
        )
        self.assertEqual(persist.await_args.kwargs["content"], "@178709680111833, beleza?")

    async def test_me_mentions_sender_even_in_private_message(self):
        sender = SimpleNamespace(id=7, name="Murillo")
        message = SimpleNamespace(
            content="manda minha foto com @me",
            user_id=7,
            group_id=None,
        )

        with patch("services.message_context.UserRepository") as repository_class:
            repository_class.return_value.find_by_id = AsyncMock(return_value=sender)
            mentions = await get_mentions_from_content(message, AsyncMock())

        self.assertEqual(mentions, [sender])
        repository_class.return_value.find_by_id.assert_awaited_once_with(7)

    async def test_me_does_not_duplicate_numeric_sender_mention(self):
        sender = SimpleNamespace(id=7, name="Murillo")
        message = SimpleNamespace(
            content="@5511999999999 e @me",
            user_id=7,
            group_id=10,
        )

        with patch("services.message_context.UserRepository") as repository_class:
            repository = repository_class.return_value
            repository.find_by_phone_or_id = AsyncMock(return_value=sender)
            repository.find_by_id = AsyncMock(return_value=sender)
            mentions = await get_mentions_from_content(message, AsyncMock())

        self.assertEqual(mentions, [sender])

    def test_webhook_context_adds_me_case_insensitively_without_duplicates(self):
        body = {
            "data": {
                "key": {
                    "id": "message-id",
                    "participantAlt": "5511888888888@s.whatsapp.net",
                },
                "messageType": "extendedTextMessage",
                "message": {"conversation": "olha @ME aqui"},
                "contextInfo": {
                    "mentionedJid": ["5511888888888@s.whatsapp.net"],
                },
            },
        }

        context = verifiy_media(body)

        self.assertEqual(context["mentions"], ["5511888888888"])


if __name__ == "__main__":
    unittest.main()
