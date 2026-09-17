import base64
import json
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import yaml
from PIL import Image

from api.routes.webhook.evolution.handles.image.generate import (
    ImageGenerationResult,
    ImageGenerationError,
    _build_image_prompt,
    _clean_image_request,
    _deduplicate_context_references,
    _exclude_gork_user,
    _fit_provider_reference_limit,
    _image_reference,
    _generate_image,
    _identity_reference_sheet,
    _model_reference_limit,
    _select_image_model,
)
from api.routes.webhook.evolution.handles.image import (
    handle_generate_sticker_command,
    handle_image_command,
)


def _encoded_image(image_format: str) -> str:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (20, 40, 60)).save(buffer, format=image_format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class ImageGenerationPipelineTests(unittest.TestCase):
    def test_conversation_schema_exposes_generated_sticker_action(self):
        schema_path = Path(__file__).parents[1] / "agents" / "schemas" / "conversation.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        action_enum = schema["properties"]["actions"]["items"]["properties"]["action"]["enum"]

        self.assertIn("generate_sticker", action_enum)

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

    def test_more_than_three_references_compacts_identities_without_dropping_people(self):
        references = [
            _image_reference(_encoded_image("PNG"), "primary", "imagem principal"),
            _image_reference(_encoded_image("JPEG"), "identity", "Ana"),
            _image_reference(_encoded_image("JPEG"), "identity", "Bruno"),
            _image_reference(_encoded_image("JPEG"), "identity", "Carla"),
        ]

        fitted = _fit_provider_reference_limit(references)

        self.assertEqual(len(fitted), 3)
        self.assertEqual(fitted[0].label, "imagem principal")
        self.assertEqual(fitted[1].label, "Ana")
        self.assertIn("Bruno", fitted[2].label)
        self.assertIn("Carla", fitted[2].label)
        self.assertEqual(fitted[2].role, "identity")
        self.assertEqual(fitted[2].mime_type, "image/jpeg")

    def test_two_context_images_and_three_people_fit_in_three_items(self):
        references = [
            _image_reference(_encoded_image("PNG"), "primary", "imagem atual"),
            _image_reference(_encoded_image("PNG"), "context", "imagem citada"),
            _image_reference(_encoded_image("JPEG"), "identity", "Ana"),
            _image_reference(_encoded_image("JPEG"), "identity", "Bruno"),
            _image_reference(_encoded_image("JPEG"), "identity", "Carla"),
        ]

        fitted = _fit_provider_reference_limit(references)

        self.assertEqual(len(fitted), 3)
        self.assertEqual(
            [reference.role for reference in fitted],
            ["primary", "context", "identity"],
        )
        for name in ("Ana", "Bruno", "Carla"):
            self.assertIn(name, fitted[2].label)

    def test_equal_current_and_quoted_images_are_sent_only_once(self):
        encoded = _encoded_image("PNG")
        references = [
            _image_reference(encoded, "primary", "imagem atual"),
            _image_reference(encoded, "context", "imagem citada"),
            _image_reference(_encoded_image("JPEG"), "identity", "Ana"),
        ]

        unique = _deduplicate_context_references(references)

        self.assertEqual([reference.label for reference in unique], ["imagem atual", "Ana"])

    def test_reference_limit_comes_from_openrouter_image_metadata(self):
        model = SimpleNamespace(
            metadata_={
                "image": {
                    "supported_parameters": {
                        "input_references": {"type": "range", "min": 0, "max": 14}
                    }
                }
            }
        )

        self.assertEqual(_model_reference_limit(model), 14)


class ImageModelFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_selects_preferred_model_that_accepts_all_references(self):
        default = SimpleNamespace(
            id=1,
            openrouter_id="x-ai/grok-imagine-image-quality",
            metadata_={
                "image": {
                    "supported_parameters": {"input_references": {"max": 3}}
                },
                "image_fallback_models": ["google/gemini-3-pro-image"],
            },
        )
        fallback = SimpleNamespace(
            id=2,
            openrouter_id="google/gemini-3-pro-image",
            metadata_={
                "image": {
                    "supported_parameters": {"input_references": {"max": 14}}
                }
            },
        )
        repository = SimpleNamespace(get_all_active=AsyncMock(return_value=[default, fallback]))

        selected, default_limit = await _select_image_model(default, repository, 5)

        self.assertIs(selected, fallback)
        self.assertEqual(default_limit, 3)

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


class ImageRequestIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = "api.routes.webhook.evolution.handles.image.generate"
        self.current_image = _encoded_image("PNG")
        self.quoted_image = _encoded_image("WEBP")
        self.profile_image = _encoded_image("JPEG")
        self.message = SimpleNamespace(
            id=10, user_id=1, group_id=None, message_id="current",
            content="!image troque o rosto mantendo o resto da foto",
            media_id=20, quoted_message_id=11,
        )
        self.quote = SimpleNamespace(
            id=11, user_id=7, message_id="quote", media_id=21,
            content="TEXTO ANTIGO QUE NAO DEVE SER ENVIADO",
        )
        self.user_repo = AsyncMock()
        self.user_repo.find_by_phone_or_id.return_value = None
        self.message_repo = AsyncMock()
        self.message_repo.find_by_id.return_value = self.quote
        self.model = SimpleNamespace(id=1, openrouter_id="test/image", metadata_={})
        self.enterContext(patch(f"{self.module}.PgConnection", return_value=AsyncMock()))
        for name, repository in {
            "AgentRepository": SimpleNamespace(find_by_name=AsyncMock(
                return_value=SimpleNamespace(prompt="EDIT SYSTEM"))),
            "UserRepository": self.user_repo,
            "MessageRepository": self.message_repo,
            "ModelConversationRepository": SimpleNamespace(
                resolve_agent_model=AsyncMock(return_value=self.model)),
            "ModelRepository": AsyncMock(),
            "CommandRepository": SimpleNamespace(
                create_command=AsyncMock(return_value=SimpleNamespace(id=9))),
            "InteractionRepository": AsyncMock(),
        }.items():
            self.enterContext(patch(f"{self.module}.{name}", return_value=repository))
        self.mentions = self.enterContext(patch(
            f"{self.module}.get_mentions_from_content", new=AsyncMock(return_value=[])))
        self.s3 = AsyncMock()
        self.s3.get_image_base64.return_value = self.profile_image
        self.enterContext(patch(f"{self.module}.S3Client", return_value=self.s3))
        self.download = self.enterContext(patch(
            f"{self.module}.download_media", new=AsyncMock(side_effect=lambda message_id: (
                {"current": self.current_image, "quote": self.quoted_image}[message_id],
                "image",
            ))))
        self.provider = self.enterContext(patch(
            f"{self.module}.generate_images", new=AsyncMock(return_value={
                "data": [{"b64_json": self.current_image}],
            })))

    async def test_only_current_request_photos_and_explicit_identity_reach_provider(self):
        person = SimpleNamespace(
            id=3, name="Ana", profile_pic_path="ana.jpg",
            phone_number="5511999999999", src_id="ana-lid",
        )
        # Mentions from the current webhook must also work in a DM.
        self.user_repo.find_by_phone_or_id.side_effect = (
            lambda identifier: person if identifier == person.phone_number else None
        )
        self.message.content = "!image coloque @5511999999999 nessa foto"
        await _generate_image(1, self.message, action_params={
            "prompt": "PEDIDO REESCRITO DO HISTORICO", "mentioned_users": [88],
        }, context={
            "image_message": "current", "image_quote": "quote",
            "mentions": [person.phone_number],
            "text_quote": (self.quote.content, "quote"),
            "history": ["CONVERSA ANTIGA"], "images": ["unrelated-image"],
        })

        payload = self.provider.await_args.args[0]
        self.assertEqual(set(payload), {"model", "prompt", "input_references"})
        self.assertTrue(payload["prompt"].endswith("USER REQUEST:\ncoloque Ana nessa foto"))
        self.assertEqual(payload["input_references"], [
            _image_reference(self.current_image, "primary", "").payload_item(),
            _image_reference(self.quoted_image, "context", "").payload_item(),
            _image_reference(self.profile_image, "identity", "").payload_item(),
        ])
        for forbidden in (self.quote.content, "CONVERSA ANTIGA", "PEDIDO REESCRITO", "unrelated-image"):
            self.assertNotIn(forbidden, str(payload))
        self.s3.get_image_base64.assert_awaited_once_with("whatsapp", "ana.jpg")
        self.user_repo.find_by_id.assert_not_awaited()
        self.message_repo.find_by_id.assert_awaited_once_with(11)

    async def test_quoting_text_never_adds_its_author_or_text(self):
        self.message.media_id = None
        self.quote.media_id = None
        await _generate_image(1, self.message, context={"text_quote": (self.quote.content, "quote")})

        payload = self.provider.await_args.args[0]
        self.assertNotIn("input_references", payload)
        self.assertNotIn(self.quote.content, payload["prompt"])
        self.user_repo.find_by_id.assert_not_awaited()
        self.s3.connect.assert_not_awaited()
        self.download.assert_not_awaited()

    async def test_quoted_image_is_base_without_current_attachment(self):
        self.message.media_id = None
        await _generate_image(1, self.message)
        payload = self.provider.await_args.args[0]
        self.assertIn("role=primary; label=imagem da mensagem citada", payload["prompt"])
        self.assertEqual(len(payload["input_references"]), 1)
        self.download.assert_awaited_once_with("quote")
        self.s3.connect.assert_not_awaited()

    async def test_image_handler_discards_agent_rewrites_even_without_literal_command(self):
        self.message.content = "troque a camiseta para azul"
        with (
            patch("api.routes.webhook.evolution.handles.image.generate_image", new=AsyncMock(
                return_value=ImageGenerationResult(success=True, image_base64=self.current_image),
            )) as generate,
            patch("api.routes.webhook.evolution.handles.image.send_image", new=AsyncMock()),
        ):
            await handle_image_command("chat", 1, self.message, action_params={
                "prompt": "HISTORICO", "mentioned_users": [88],
            })
        generate.assert_awaited_once_with(
            1, self.message, action_params=None, context=None, feedback_remote_id="chat",
        )

    async def test_image_action_cannot_select_an_old_message(self):
        from api.routes.webhook.evolution.handles.chat import _dispatch_action

        module = "api.routes.webhook.evolution.handles.chat"
        context = {"image_message": "current"}
        with (
            patch(f"{module}.get_disabled_command_message", new=AsyncMock(return_value=None)),
            patch(f"{module}.MessageRepository", return_value=self.message_repo),
            patch(f"{module}.handle_image_command", new=AsyncMock()) as handle,
        ):
            await _dispatch_action(
                action_type="image",
                action={"parameters": {"message_id": 999, "prompt": "OLD REQUEST"}},
                remote_id="chat", user=SimpleNamespace(id=1), db=AsyncMock(),
                db_message=self.message, scheduler=None, context=context, group_id=None,
            )
        handle.assert_awaited_once_with(
            remote_id="chat", user_id=1, db_message=self.message, context=context,
        )
        self.message_repo.find_by_id.assert_not_awaited()
        self.message_repo.find_by_message_id.assert_not_awaited()


class IdentityReferencePreservationTests(unittest.TestCase):
    def test_reference_limit_never_silently_drops_an_identity(self):
        references = [
            _image_reference(_encoded_image("PNG"), "primary", "base"),
            _image_reference(_encoded_image("JPEG"), "identity", "Ana"),
        ]
        with self.assertRaises(ImageGenerationError) as raised:
            _fit_provider_reference_limit(references, limit=1)
        self.assertEqual(raised.exception.code, "input_reference_limit")

    def test_identity_sheet_preserves_edges_of_portrait_photos(self):
        photo = Image.new("RGB", (100, 300), "blue")
        photo.paste("red", (0, 0, 100, 50))
        photo.paste("green", (0, 250, 100, 300))
        buffer = BytesIO()
        photo.save(buffer, format="PNG")
        reference = _image_reference(base64.b64encode(buffer.getvalue()).decode(), "identity", "Ana")
        sheet = _identity_reference_sheet([reference] * 4)
        with Image.open(BytesIO(base64.b64decode(sheet.image_base64))) as result:
            self.assertEqual(result.size, (1536, 1024))
            self.assertGreater(result.getpixel((256, 20))[0], 220)
            self.assertGreater(result.getpixel((256, 490))[1], 100)
            self.assertTrue(all(channel > 240 for channel in result.getpixel((10, 256))))
        self.assertIn("row 2, column 1: Ana", sheet.label)


class GeneratedStickerPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_image_is_passed_directly_to_sticker_with_caption(self):
        image_base64 = _encoded_image("PNG")
        message = SimpleNamespace(message_id="request-id", content="gera uma figurinha")
        db = AsyncMock()
        params = {
            "prompt": "um homem empinando uma moto",
            "caption": "CONFIA NO PAI",
            "fill": True,
            "no_background": True,
        }

        with (
            patch(
                "api.routes.webhook.evolution.handles.image.generate_image",
                new=AsyncMock(
                    return_value=ImageGenerationResult(
                        success=True,
                        image_base64=image_base64,
                    )
                ),
            ) as generate,
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.static_sticker",
                new=AsyncMock(return_value="sticker-base64"),
            ) as make_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_sticker",
                new=AsyncMock(),
            ) as send_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_image",
                new=AsyncMock(),
            ) as send_image,
        ):
            await handle_generate_sticker_command(
                remote_id="group-id",
                user_id=7,
                db_message=message,
                db=db,
                action_params=params,
            )

        generate.assert_awaited_once_with(
            7,
            message,
            action_params=params,
            context=None,
            feedback_remote_id="group-id",
        )
        sticker_call = make_sticker.await_args.kwargs
        self.assertEqual(
            sticker_call["source_image_bytes"],
            base64.b64decode(image_base64),
        )
        self.assertEqual(sticker_call["caption_text"], "CONFIA NO PAI")
        self.assertTrue(sticker_call["fill"])
        self.assertTrue(sticker_call["remove_background"])
        send_sticker.assert_awaited_once_with("group-id", "sticker-base64")
        send_image.assert_not_awaited()

    async def test_image_generation_failure_does_not_attempt_sticker(self):
        message = SimpleNamespace(message_id="request-id", content="gera uma figurinha")

        with (
            patch(
                "api.routes.webhook.evolution.handles.image.generate_image",
                new=AsyncMock(
                    return_value=ImageGenerationResult(
                        success=False,
                        user_message="Falhou bonito.",
                    )
                ),
            ),
            patch(
                "api.routes.webhook.evolution.handles.image.sticker_static.static_sticker",
                new=AsyncMock(),
            ) as make_sticker,
            patch(
                "api.routes.webhook.evolution.handles.image.send_message",
                new=AsyncMock(),
            ) as send_message,
        ):
            await handle_generate_sticker_command(
                remote_id="group-id",
                user_id=7,
                db_message=message,
                db=AsyncMock(),
                action_params={"prompt": "uma cena"},
            )

        make_sticker.assert_not_awaited()
        send_message.assert_awaited_once_with(
            "group-id",
            "Falhou bonito.",
            "request-id",
        )

if __name__ == "__main__":
    unittest.main()
