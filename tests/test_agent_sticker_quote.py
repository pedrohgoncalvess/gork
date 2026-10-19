import base64
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from api.routes.webhook.waha.handles.chat import _dispatch_action


class AgentStickerQuoteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.current = SimpleNamespace(
            id=200, message_id="request-id", user_id=7, group_id=1,
            content="faz uma figurinha daquela mensagem", media_id=55,
            quoted_message_id=None,
        )
        self.selected = SimpleNamespace(
            id=100, message_id="selected-id", user_id=20, group_id=1,
            content="Hoje o café ficou perfeito", media_id=None,
            quoted_message_id=90,
        )
        profile = BytesIO()
        Image.new("RGB", (32, 32), "red").save(profile, format="PNG")
        self.profile_base64 = base64.b64encode(profile.getvalue()).decode()

    async def dispatch(self, params):
        return await _dispatch_action(
            action_type="sticker", action={"parameters": params},
            remote_id="group", user=SimpleNamespace(id=7), db=Mock(),
            db_message=self.current, scheduler=Mock(), group_id=1,
            context={"image_message": "unrelated-image", "text_quote": "unrelated caption"},
        )

    async def test_selected_text_uses_selected_authors_photo_and_words(self):
        repo = Mock()
        repo.find_by_id = AsyncMock(return_value=self.selected)
        with (
            patch("api.routes.webhook.waha.handles.chat.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch("api.routes.webhook.waha.handles.chat.is_feature_blocked", new=AsyncMock(return_value=False)),
            patch("api.routes.webhook.waha.handles.chat.MessageRepository", return_value=repo),
            patch("api.routes.webhook.waha.handles.image.MessageRepository", return_value=repo),
            patch("api.routes.webhook.waha.handles.image.sticker_static.MessageRepository", return_value=repo),
            patch("api.routes.webhook.waha.handles.image.sticker_static.UserRepository") as users,
            patch("api.routes.webhook.waha.handles.image.sticker_static.S3Client") as s3,
            patch("api.routes.webhook.waha.handles.image.sticker_static.add_caption_to_image", side_effect=lambda image, *args, **kwargs: image) as caption,
            patch("api.routes.webhook.waha.handles.image.sticker_static._random_image", new=AsyncMock()) as random_image,
            patch("api.routes.webhook.waha.handles.image.send_sticker", new=AsyncMock()) as send,
        ):
            users.return_value.find_by_id = AsyncMock(return_value=SimpleNamespace(profile_pic_path="profile/selected.jpeg"))
            s3.return_value.connect = AsyncMock()
            s3.return_value.get_image_base64 = AsyncMock(return_value=self.profile_base64)
            await self.dispatch({"message_id": 100})

        users.return_value.find_by_id.assert_awaited_once_with(20)
        s3.return_value.get_image_base64.assert_awaited_once_with("whatsapp", "profile/selected.jpeg")
        self.assertEqual(caption.call_args.args[1], self.selected.content)
        random_image.assert_not_awaited()
        send.assert_awaited_once()
        self.assertEqual(self.selected.quoted_message_id, 90)
        self.assertEqual(self.selected.content, "Hoje o café ficou perfeito")
        self.assertEqual(self.current.media_id, 55)

    async def test_selected_media_receives_virtual_quote_without_current_webhook_media(self):
        self.selected.media_id = 33
        with (
            patch("api.routes.webhook.waha.handles.chat.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch("api.routes.webhook.waha.handles.chat.is_feature_blocked", new=AsyncMock(return_value=False)),
            patch("api.routes.webhook.waha.handles.chat.MessageRepository") as repo,
            patch("api.routes.webhook.waha.handles.chat.handle_sticker_command", new=AsyncMock()) as handler,
        ):
            repo.return_value.find_by_id = AsyncMock(return_value=self.selected)
            await self.dispatch({"message_id": 100})

        request = handler.await_args.kwargs["db_message"]
        self.assertEqual(request.quoted_message_id, 100)
        self.assertIsNone(request.media_id)
        self.assertEqual(request.content, "!sticker")
        self.assertEqual(handler.await_args.kwargs["context"], {})

    async def test_missing_or_other_group_message_does_not_fallback_to_current_message(self):
        self.selected.group_id = 2
        for selected in (None, self.selected):
            with (
                patch("api.routes.webhook.waha.handles.chat.get_disabled_command_message", new=AsyncMock(return_value=None)),
                patch("api.routes.webhook.waha.handles.chat.is_feature_blocked", new=AsyncMock(return_value=False)),
                patch("api.routes.webhook.waha.handles.chat.MessageRepository") as repo,
                patch("api.routes.webhook.waha.handles.chat.handle_sticker_command", new=AsyncMock()) as handler,
                patch("api.routes.webhook.waha.handles.chat.send_message", new=AsyncMock()) as send,
            ):
                repo.return_value.find_by_id = AsyncMock(return_value=selected)
                await self.dispatch({"message_id": 100})
            handler.assert_not_awaited()
            send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
