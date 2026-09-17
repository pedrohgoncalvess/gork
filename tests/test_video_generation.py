import unittest
import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from api.routes.webhook.evolution.handles.video import (
    VideoRequestError,
    _quoted_media_reference,
    _reference_images,
    _replace_user_references,
    normalize_quality,
    resolve_video_options,
    video_submit_error_message,
)
from external.openrouter import OpenRouterVideoError, submit_video


class VideoOptionsTests(unittest.TestCase):
    capabilities = {
        "supported_durations": [5, 10],
        "supported_resolutions": ["1080p", "480p", "720p", "4K"],
        "supported_aspect_ratios": ["1:1", "16:9"],
        "generate_audio": True,
    }

    def test_defaults_to_five_seconds_lowest_supported_quality_and_no_audio(self):
        options = resolve_video_options({}, self.capabilities)

        self.assertEqual(options.duration, 5)
        self.assertEqual(options.resolution, "480p")
        self.assertEqual(options.aspect_ratio, "16:9")
        self.assertFalse(options.generate_audio)

    def test_explicit_duration_audio_and_quality(self):
        options = resolve_video_options(
            {"duration": 10, "audio": "t", "quality": "4k"},
            self.capabilities,
        )

        self.assertEqual(options.duration, 10)
        self.assertEqual(options.resolution, "4K")
        self.assertTrue(options.generate_audio)

    def test_duration_above_ten_is_rejected_before_model_capability(self):
        with self.assertRaisesRegex(VideoRequestError, "entre 1 e 10"):
            resolve_video_options({"duration": 11}, self.capabilities)

    def test_unsupported_model_duration_is_rejected(self):
        with self.assertRaisesRegex(VideoRequestError, "não suporta 7s"):
            resolve_video_options({"duration": 7}, self.capabilities)

    def test_unsupported_quality_is_rejected(self):
        with self.assertRaisesRegex(VideoRequestError, "não suporta 2K"):
            resolve_video_options({"quality": "2k"}, self.capabilities)

    def test_audio_is_rejected_when_model_does_not_support_it(self):
        capabilities = {**self.capabilities, "generate_audio": False}
        with self.assertRaisesRegex(VideoRequestError, "não oferece"):
            resolve_video_options({"audio": True}, capabilities)

    def test_public_quality_values_are_normalized(self):
        expected = {
            "480": "480p",
            "720p": "720p",
            1080: "1080p",
            "2K": "2K",
            "4k": "4K",
        }
        for value, normalized in expected.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_quality(value), normalized)


class VideoReferenceTests(unittest.TestCase):
    def test_mentions_and_me_are_replaced_with_names_in_prompt(self):
        mentioned = SimpleNamespace(
            name="Maria",
            phone_number="5511999999999",
            src_id="123456789012345",
        )
        sender = SimpleNamespace(name="Pedro")

        result = _replace_user_references(
            "faça @5511999999999@s.whatsapp.net correr com @me",
            [mentioned],
            sender,
        )

        self.assertEqual(result, "faça Maria correr com Pedro")


class VideoReferenceUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_picture_is_published_as_temporary_https_reference(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, format="JPEG")
        client = Mock()
        client.connect = AsyncMock()
        client.get_image_base64 = AsyncMock(
            return_value=base64.b64encode(buffer.getvalue()).decode("ascii")
        )
        user = SimpleNamespace(name="Maria", profile_pic_path="profiles/maria.jpg")

        with (
            patch("api.routes.webhook.evolution.handles.video.S3Client", return_value=client),
            patch(
                "api.routes.webhook.evolution.handles.video.upload_temporary_file",
                new=AsyncMock(return_value="https://d.tmpfile.link/reference.jpg"),
            ) as upload,
        ):
            references = await _reference_images([user])

        self.assertEqual(
            references,
            [{
                "type": "image_url",
                "image_url": {"url": "https://d.tmpfile.link/reference.jpg"},
            }],
        )
        upload.assert_awaited_once()

    async def test_quoted_image_is_uploaded_as_image_reference(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), "blue").save(buffer, format="PNG")
        db_message = SimpleNamespace(quoted_message_id=41)
        quoted_message = SimpleNamespace(media_id=7, message_id="quoted-message")
        media = SimpleNamespace(
            type="image",
            name="photo.png",
            bucket="whatsapp",
            path="media/photo.png",
        )
        message_repo = Mock(find_by_id=AsyncMock(return_value=quoted_message))
        media_repo = Mock(find_by_id=AsyncMock(return_value=media))
        s3_client = Mock(
            connect=AsyncMock(),
            get_image_base64=AsyncMock(
                return_value=base64.b64encode(buffer.getvalue()).decode("ascii")
            ),
        )

        with (
            patch("api.routes.webhook.evolution.handles.video.MessageRepository", return_value=message_repo),
            patch("api.routes.webhook.evolution.handles.video.MediaRepository", return_value=media_repo),
            patch("api.routes.webhook.evolution.handles.video.S3Client", return_value=s3_client),
            patch(
                "api.routes.webhook.evolution.handles.video.upload_temporary_file",
                new=AsyncMock(return_value="https://d.tmpfile.link/photo.png"),
            ),
        ):
            reference = await _quoted_media_reference(db_message, Mock())

        self.assertEqual(reference, ({
            "type": "image_url",
            "image_url": {"url": "https://d.tmpfile.link/photo.png"},
        }, "image"))

    async def test_quoted_video_is_uploaded_as_video_reference(self):
        video_bytes = b"\x00\x00\x00\x18ftypmp42test"
        db_message = SimpleNamespace(quoted_message_id=42)
        quoted_message = SimpleNamespace(media_id=8, message_id="quoted-video")
        media = SimpleNamespace(
            type="video",
            name="clip.mp4",
            bucket="whatsapp",
            path="media/clip.mp4",
        )
        message_repo = Mock(find_by_id=AsyncMock(return_value=quoted_message))
        media_repo = Mock(find_by_id=AsyncMock(return_value=media))
        s3_client = Mock(
            connect=AsyncMock(),
            get_image_base64=AsyncMock(
                return_value=base64.b64encode(video_bytes).decode("ascii")
            ),
        )
        upload = AsyncMock(return_value="https://d.tmpfile.link/clip.mp4")

        with (
            patch("api.routes.webhook.evolution.handles.video.MessageRepository", return_value=message_repo),
            patch("api.routes.webhook.evolution.handles.video.MediaRepository", return_value=media_repo),
            patch("api.routes.webhook.evolution.handles.video.S3Client", return_value=s3_client),
            patch("api.routes.webhook.evolution.handles.video.upload_temporary_file", new=upload),
        ):
            reference = await _quoted_media_reference(db_message, Mock())

        self.assertEqual(reference, ({
            "type": "video_url",
            "video_url": {"url": "https://d.tmpfile.link/clip.mp4"},
        }, "video"))
        upload.assert_awaited_once_with(
            video_bytes,
            "quoted-video-reference.mp4",
            "video/mp4",
        )


class OpenRouterVideoClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_error_extracts_nested_provider_code_and_redacts_prompt(self):
        nested_error = {
            "error": {
                "code": "InputImageSensitiveContentDetected.PrivacyInformation",
                "message": "The input image may contain real person.",
            }
        }
        response = Mock(status_code=400)
        response.text = '{"error":{"message":"provider rejected request"}}'
        response.json.return_value = {
            "error": {"message": "HTTP 400: " + json.dumps(nested_error)}
        }
        client = AsyncMock()
        client.post.return_value = response
        context_manager = AsyncMock()
        context_manager.__aenter__.return_value = client

        with (
            patch("external.openrouter.httpx.AsyncClient", return_value=context_manager),
            patch("external.openrouter.openrouter_logger.error", new=AsyncMock()) as log_error,
        ):
            with self.assertRaises(OpenRouterVideoError) as raised:
                await submit_video({"model": "video/model", "prompt": "private prompt"})

        self.assertEqual(
            raised.exception.provider_code,
            "InputImageSensitiveContentDetected.PrivacyInformation",
        )
        self.assertIn("real person", raised.exception.provider_message)
        log_error.assert_awaited_once()
        logged_message = log_error.await_args.args[2]
        self.assertNotIn("private prompt", logged_message)
        self.assertIn("prompt_characters", logged_message)


class VideoErrorMessageTests(unittest.TestCase):
    def test_real_person_privacy_rejection_has_actionable_message(self):
        error = OpenRouterVideoError(
            400,
            "The input image may contain real person.",
            "InputImageSensitiveContentDetected.PrivacyInformation",
        )

        message = video_submit_error_message(error)

        self.assertIn("pessoa real", message)
        self.assertIn("sem a foto/menção", message)

    def test_rate_limit_has_retry_later_message(self):
        message = video_submit_error_message(OpenRouterVideoError(429, "rate limited"))

        self.assertIn("Aguarde", message)


if __name__ == "__main__":
    unittest.main()
