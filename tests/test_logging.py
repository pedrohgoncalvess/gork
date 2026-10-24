import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from external.openrouter import completions, embeddings, generate_images
from log.config import StructuredLogger


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_warnings_and_errors_write_readable_records(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("log.config.get_env_var", return_value=None):
                logger = StructuredLogger()
            logger._log_file_dir_ = directory
            logger._log_path_ = str(Path(directory) / "application.log")
            await logger.info("Webhook", "Received", "private message")
            self.assertFalse(Path(logger._log_path_).exists())

            with patch.dict("os.environ", {"DATA_ENCRYPTION_KEY": "invalid"}):
                await logger.warn("Database", "Retry", "attempt=2")
                await logger.warning("Media", "Unavailable", "status=404")
                await logger.error("OpenRouter", "Timeout", "TimeoutError")

            records = Path(logger._log_path_).read_text(encoding="utf-8")
            self.assertNotIn("private message", records)
            self.assertNotIn("INFO", records)
            self.assertNotIn("gork:v1:", records)
            self.assertIn("TimeoutError", records)
            self.assertEqual(len(records.splitlines()), 4)
            self.assertRegex(records, r"ERROR \| \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| OpenRouter \| Timeout")

    async def test_provider_errors_omit_request_and_response_content(self):
        private = "private conversation content"
        for operation, arguments in (
            (completions, ({"model": "test/model", "messages": [{"role": "user", "content": private}]},)),
            (generate_images, ({"model": "test/model", "prompt": private},)),
            (embeddings, (private, "test/model")),
        ):
            with self.subTest(operation=operation.__name__):
                client = AsyncMock()
                client.post.return_value = httpx.Response(
                    400, json={"error": private},
                    request=httpx.Request("POST", "https://openrouter.ai/api/v1/test"),
                )
                context = AsyncMock()
                context.__aenter__.return_value = client
                with (
                    patch("external.openrouter.httpx.AsyncClient", return_value=context),
                    patch("external.openrouter.openrouter_logger.error", new=AsyncMock()) as error_log,
                    patch("external.openrouter.openrouter_logger.info", new=AsyncMock()) as info_log,
                ):
                    with self.assertRaises(httpx.HTTPStatusError):
                        await operation(*arguments)
                self.assertTrue(error_log.await_count)
                self.assertNotIn(private, str(error_log.await_args_list))
                self.assertIn("test/model", str(error_log.await_args_list))
                info_log.assert_not_awaited()

    async def test_parse_errors_omit_model_output(self):
        from agents._shared.conversation_parser import parse_gork_response
        from agents.filter.parser import parse_filter_response

        for parser in (parse_gork_response, parse_filter_response):
            with self.subTest(parser=parser.__name__):
                with patch(f"{parser.__module__}.logger.error", new=AsyncMock()) as log:
                    with self.assertRaises(ValueError):
                        await parser('private conversation content {"incomplete":')
                self.assertTrue(log.await_count)
                self.assertNotIn("private conversation content", str(log.await_args_list))
