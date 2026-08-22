import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.message_context import get_mentions_from_content, verifiy_media


class MentionResolutionTests(unittest.IsolatedAsyncioTestCase):
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
