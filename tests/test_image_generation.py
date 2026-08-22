import base64
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import yaml
from PIL import Image

from api.routes.webhook.evolution.handles.image.generate import (
    ImageGenerationError,
    _build_image_prompt,
    _clean_image_request,
    _exclude_gork_user,
    _image_reference,
    _include_quoted_author,
)


def _encoded_image(image_format: str) -> str:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (20, 40, 60)).save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ImageGenerationPipelineTests(unittest.TestCase):
    def test_modify_image_agent_is_registered_for_fresh_installations(self):
        config_path = Path(__file__).parents[1] / "agents" / "agents.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        agents = {agent["name"]: agent for agent in config["agents"]}

        self.assertIn("modify-image", agents)
        self.assertEqual(
            agents["modify-image"]["prompt_path"],
            "agents/prompts/modify-image.md",
        )

    def test_image_reference_detects_real_mime_type(self):
        png_reference = _image_reference(
            _encoded_image("PNG"),
            "primary",
            "imagem principal",
        )
        webp_reference = _image_reference(
            _encoded_image("WEBP"),
            "context",
            "imagem citada",
        )

        self.assertEqual(png_reference.mime_type, "image/png")
        self.assertEqual(webp_reference.mime_type, "image/webp")
        self.assertTrue(
            png_reference.payload_item()["image_url"]["url"].startswith(
                "data:image/png;base64,"
            )
        )

    def test_invalid_input_reference_is_rejected_before_provider_call(self):
        with self.assertRaises(ImageGenerationError) as raised:
            _image_reference("bm90IGFuIGltYWdl", "primary", "imagem principal")

        self.assertEqual(raised.exception.code, "invalid_input_reference")

    def test_prompt_manifest_uses_reference_roles_and_order(self):
        references = [
            _image_reference(_encoded_image("PNG"), "primary", "base"),
            _image_reference(_encoded_image("JPEG"), "identity", "Pedro"),
        ]

        prompt = _build_image_prompt("SYSTEM", "coloque Pedro na praia", references)

        self.assertIn("Reference [1]: role=primary; label=base", prompt)
        self.assertIn("Reference [2]: role=identity; label=Pedro", prompt)
        self.assertTrue(prompt.endswith("USER REQUEST:\ncoloque Pedro na praia"))

    def test_clean_request_replaces_mentions_before_removing_command(self):
        gork = SimpleNamespace(
            phone_number="5500000000000",
            src_id="gork-lid",
        )
        pedro = SimpleNamespace(
            phone_number="5511999999999",
            src_id="pedro-lid",
            name="Pedro",
        )

        request = _clean_image_request(
            "!IMAGE coloque @5511999999999 ao lado do Gork @5500000000000",
            gork,
            [pedro],
        )

        self.assertEqual(request, "coloque Pedro ao lado do Gork")

    def test_clean_request_preserves_colon_text(self):
        request = _clean_image_request(
            "!image uma placa com texto:dead e proporção:vertical",
            None,
            [],
        )

        self.assertEqual(
            request,
            "uma placa com texto:dead e proporção:vertical",
        )

    def test_gork_is_not_an_identity_reference(self):
        gork = SimpleNamespace(id=1, name="Gork")
        joao = SimpleNamespace(id=2, name="João")

        references = _exclude_gork_user([gork, joao], gork)

        self.assertEqual(references, [joao])

    def test_me_is_replaced_with_request_sender_name(self):
        sender = SimpleNamespace(
            id=3,
            phone_number="5511888888888",
            src_id="sender-lid",
            name="Murillo",
        )

        request = _clean_image_request(
            "!image coloque @me nessa foto",
            None,
            [sender],
            me_user=sender,
        )

        self.assertEqual(request, "coloque Murillo nessa foto")


class QuotedAuthorReferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_quoted_author_is_added_as_identity_reference(self):
        quoted_user = SimpleNamespace(id=7, name="Maria")
        repository = SimpleNamespace(find_by_id=AsyncMock(return_value=quoted_user))
        referenced_users = []

        await _include_quoted_author(
            referenced_users,
            SimpleNamespace(user_id=7),
            SimpleNamespace(id=99),
            repository,
        )

        self.assertEqual(referenced_users, [quoted_user])
        repository.find_by_id.assert_awaited_once_with(7)

    async def test_gork_and_existing_users_are_not_added_again(self):
        existing_user = SimpleNamespace(id=7, name="Maria")
        repository = SimpleNamespace(find_by_id=AsyncMock())
        referenced_users = [existing_user]

        await _include_quoted_author(
            referenced_users,
            SimpleNamespace(user_id=7),
            SimpleNamespace(id=99),
            repository,
        )
        await _include_quoted_author(
            referenced_users,
            SimpleNamespace(user_id=99),
            SimpleNamespace(id=99),
            repository,
        )

        self.assertEqual(referenced_users, [existing_user])
        repository.find_by_id.assert_not_awaited()

    async def test_quoted_author_is_ignored_when_quote_already_has_image(self):
        pedro = SimpleNamespace(id=7, name="Pedro")
        repository = SimpleNamespace(find_by_id=AsyncMock(return_value=pedro))
        referenced_users = []

        await _include_quoted_author(
            referenced_users,
            SimpleNamespace(user_id=7),
            SimpleNamespace(id=99),
            repository,
            quoted_has_image_reference=True,
        )

        self.assertEqual(referenced_users, [])
        repository.find_by_id.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
