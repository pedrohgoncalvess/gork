import base64
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from api.routes.webhook.waha.handles.core import get_explicit_command_feature, has_explicit_command
from api.routes.webhook.waha.handles.image.deactivate import handle_deactivate_command, render_deactivated_image
from api.routes.webhook.waha.processors.common import process_commands


MODULE = "api.routes.webhook.waha.handles.image.deactivate"


def photo_bytes():
    buffer = BytesIO()
    Image.new("RGB", (418, 240), (240, 60, 20)).save(buffer, format="PNG")
    return buffer.getvalue()


class DeactivateRenderTests(unittest.TestCase):
    def test_grayscale_photo_preserves_size_and_appends_dark_footer(self):
        result = Image.open(BytesIO(base64.b64decode(render_deactivated_image(photo_bytes()))))
        self.assertEqual(result.size, (418, 298))
        red, green, blue = result.getpixel((100, 100))
        self.assertEqual(red, green)
        self.assertEqual(green, blue)
        self.assertEqual(result.getpixel((417, 297)), (54, 57, 59))
        self.assertGreater(len(set(result.crop((20, 240, 290, 298)).getdata())), 2)

    def test_command_is_recognized(self):
        self.assertTrue(has_explicit_command("!deactivate @5511999999999"))
        self.assertEqual(get_explicit_command_feature("!deactivate"), "deactivate")


class DeactivateHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.message = SimpleNamespace(message_id="request", quoted_message_id=None, media_id=None, content="!deactivate")
        self.bot = SimpleNamespace(phone_number="5511888888888", src_id="123456789012345")
        self.enterContext(patch(f"{MODULE}.get_instance_number", new=AsyncMock(return_value=self.bot.phone_number)))
        self.enterContext(patch(f"{MODULE}.UserRepository.find_by_phone", new=AsyncMock(return_value=self.bot)))

    async def test_context_quote_works_without_saved_message(self):
        with (
            patch(f"{MODULE}.download_media", new=AsyncMock(return_value=(base64.b64encode(photo_bytes()).decode(), "image"))) as download,
            patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
        ):
            await handle_deactivate_command("chat", self.message, Mock(), {"image_quote": "quoted-id"})
        download.assert_awaited_once_with("quoted-id")
        self.assertEqual(send.await_args.kwargs["mimetype"], "image/png")

    async def test_mention_uses_saved_profile_even_in_private_chat(self):
        self.message.content += " @5511999999999"
        with (
            patch(f"{MODULE}.UserRepository.find_by_phone_or_id", new=AsyncMock(return_value=SimpleNamespace(profile_pic_path="profile.png"))) as lookup,
            patch(f"{MODULE}._stored_image", new=AsyncMock(return_value=photo_bytes())) as stored,
            patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
        ):
            await handle_deactivate_command("chat", self.message, Mock())
        lookup.assert_awaited_once_with("5511999999999")
        stored.assert_awaited_once_with("whatsapp", "profile.png")
        send.assert_awaited_once()

    async def test_failed_download_falls_back_to_saved_quoted_media(self):
        self.message.quoted_message_id = 10
        with (
            patch(f"{MODULE}.MessageRepository.find_by_id", new=AsyncMock(return_value=SimpleNamespace(message_id="quoted-id", media_id=20))),
            patch(f"{MODULE}.download_media", new=AsyncMock(side_effect=RuntimeError("expired"))),
            patch(f"{MODULE}.MediaRepository.find_by_id", new=AsyncMock(return_value=SimpleNamespace(bucket="whatsapp", path="saved.png"))),
            patch(f"{MODULE}._stored_image", new=AsyncMock(return_value=photo_bytes())) as stored,
            patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
        ):
            await handle_deactivate_command("chat", self.message, Mock())
        stored.assert_awaited_once_with("whatsapp", "saved.png")
        send.assert_awaited_once()

    async def test_mention_without_profile_explains_usage(self):
        self.message.content += " @5511999999999"
        self.enterContext(patch(f"{MODULE}.UserRepository.find_by_phone_or_id", new=AsyncMock(return_value=None)))
        with patch(f"{MODULE}.send_message", new=AsyncMock()) as send:
            await handle_deactivate_command("chat", self.message, Mock())
        self.assertIn("!deactivate @usuário", send.await_args.args[1])

    async def test_bot_phone_and_lid_mentions_are_ignored_before_target(self):
        self.message.content += f" @{self.bot.phone_number} @{self.bot.src_id} @5511999999999"
        with (
            patch(f"{MODULE}.UserRepository.find_by_phone_or_id", new=AsyncMock(return_value=SimpleNamespace(profile_pic_path="target.png"))) as lookup,
            patch(f"{MODULE}._stored_image", new=AsyncMock(return_value=photo_bytes())) as stored,
            patch(f"{MODULE}.send_image", new=AsyncMock()),
        ):
            await handle_deactivate_command("chat", self.message, Mock())
        lookup.assert_awaited_once_with("5511999999999")
        stored.assert_awaited_once_with("whatsapp", "target.png")

    async def test_clean_command_and_bot_only_mentions_use_random_photo(self):
        for content in ("!deactivate", f"@{self.bot.phone_number} !deactivate", f"!deactivate @{self.bot.src_id}"):
            with (
                self.subTest(content=content),
                patch(f"{MODULE}._random_photo", new=AsyncMock(return_value=photo_bytes())) as random_photo,
                patch(f"{MODULE}.UserRepository.find_by_phone_or_id", new=AsyncMock()) as lookup,
                patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
            ):
                self.message.content = content
                await handle_deactivate_command("chat", self.message, Mock())
                random_photo.assert_awaited_once()
                lookup.assert_not_awaited()
                send.assert_awaited_once()

    async def test_corrupt_source_reports_error_without_sending_image(self):
        with (
            patch(f"{MODULE}.download_media", new=AsyncMock(return_value=(base64.b64encode(b"invalid").decode(), "image"))),
            patch(f"{MODULE}.logger.error", new=AsyncMock()),
            patch(f"{MODULE}.send_message", new=AsyncMock()) as message,
            patch(f"{MODULE}.send_image", new=AsyncMock()) as send,
        ):
            await handle_deactivate_command("chat", self.message, Mock(), {"image_quote": "quote"})
        send.assert_not_awaited()
        message.assert_awaited_once()

    async def test_dispatch_routes_command_and_checks_disabled_rule(self):
        module = "api.routes.webhook.waha.processors.common"
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)) as rule,
            patch(f"{module}.handle_deactivate_command", new=AsyncMock()) as handler,
        ):
            db = Mock()
            await process_commands("!deactivate", "chat", "request", SimpleNamespace(id=1), {}, None, db, Mock(), {}, self.message)
        self.assertEqual(rule.await_args.kwargs["command"], "deactivate")
        handler.assert_awaited_once_with("chat", self.message, db, {})
