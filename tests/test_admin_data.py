from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from api.admin import data


class AdminDataTests(unittest.IsolatedAsyncioTestCase):
    def database(self, items=()):
        result = Mock()
        result.mappings.return_value = items
        return SimpleNamespace(scalar=AsyncMock(return_value=len(items)),
                               execute=AsyncMock(return_value=result), commit=AsyncMock())

    async def browse(self, db, **changes):
        args = dict(kind="messages", group_id=None, user_id=None, start=None, end=None,
                    q="", offset=0, limit=30, db=db)
        args.update(changes)
        return await data.browse(**args)

    async def test_filters_apply_to_count_and_page_and_exclude_deleted(self):
        db = self.database()
        await self.browse(db, kind="attachments", group_id=4, user_id=8,
                          start=datetime.fromisoformat("2026-10-01T00:00:00-03:00"),
                          end=datetime.fromisoformat("2026-10-02T00:00:00-03:00"), offset=30)
        for stmt in (db.scalar.await_args.args[0], db.execute.await_args.args[0]):
            sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
            for expected in ("deleted_at IS NULL", "group_id = 4", "user_id = 8", "chat_user_id = 8",
                             "media.id IS NOT NULL", "2026-10-01 03:00:00", "2026-10-02 03:00:00"):
                self.assertIn(expected, sql)

    async def test_semantic_attachments_use_stored_description_vectors(self):
        db = self.database()
        with patch.object(data, "vectors", new=AsyncMock(return_value=[[1.0] * 2560])):
            await self.browse(db, kind="attachments", q="viagem")
        sql = str(db.execute.await_args.args[0])
        self.assertIn("description_embedding <=>", sql)
        self.assertIn("description_embedding IS NOT NULL", sql)
        db.commit.assert_not_awaited()

    async def test_messages_index_pending_text_then_rank_and_report_remaining(self):
        db = self.database()
        pending = Mock()
        pending.all.return_value = [SimpleNamespace(id=9, content="Vamos viajar", updated_at=None)]
        result = Mock()
        result.mappings.return_value = []
        db.execute.side_effect = [pending, Mock(), result]
        db.scalar.side_effect = [15, 1]
        with patch.object(data, "vectors", new=AsyncMock(return_value=[[1.0] * 2560])) as vectors:
            response = await self.browse(db, q="viagem", index_messages=True)
        self.assertEqual(vectors.await_args_list[1].args[1], ["Vamos viajar"])
        db.commit.assert_awaited_once()
        self.assertIn(b'"indexing_remaining":15', response.body)
        self.assertIn("content_embedding <=>", str(db.execute.await_args.args[0]))

    async def test_invalid_and_naive_windows_fail_before_querying(self):
        for start, end in ((datetime(2026, 1, 1), None),
                           (datetime.fromisoformat("2026-02-01T00:00:00Z"), datetime.fromisoformat("2026-01-01T00:00:00Z"))):
            db = self.database()
            with self.assertRaises(HTTPException) as error:
                await self.browse(db, start=start, end=end)
            self.assertEqual(error.exception.status_code, 422)
            db.execute.assert_not_awaited()

    async def test_semantic_pagination_does_not_index_or_change_ranking(self):
        db = self.database()
        with patch.object(data, "vectors", new=AsyncMock(return_value=[[1.0] * 2560])) as vectors:
            await self.browse(db, q="viagem", offset=30)
        vectors.assert_awaited_once()
        db.commit.assert_not_awaited()
        self.assertEqual(db.execute.await_count, 1)
        self.assertIn("content_embedding <=>", str(db.execute.await_args.args[0]))

    async def test_documents_download_and_storage_stream_is_closed(self):
        db = self.database()
        db.scalar.return_value = SimpleNamespace(name="arquivo.html", bucket="whatsapp", path="folder/file.html")
        storage_response = Mock()
        storage_response.stream.return_value = iter([b"<script>example</script>"])
        storage = SimpleNamespace(decrypt_object=lambda response, bucket, path: response.stream(64 * 1024), connect=AsyncMock(), client=SimpleNamespace(get_object=Mock(return_value=storage_response)))
        with patch.object(data, "S3Client", return_value=storage):
            response = await data.media(1, False, db)
            chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(chunks, [b"<script>example</script>"])
        self.assertTrue(response.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(response.headers["cache-control"], "no-store")
        storage_response.close.assert_called_once()
        storage_response.release_conn.assert_called_once()

    async def test_embedding_failures_are_sanitized(self):
        repo = Mock()
        repo.get_default_embedding_model = AsyncMock(return_value=SimpleNamespace(openrouter_id="model"))
        with patch.object(data, "ModelRepository", return_value=repo), patch.object(data, "embeddings", new=AsyncMock(side_effect=RuntimeError("secret"))):
            with self.assertRaises(HTTPException) as error:
                await data.vectors(self.database(), ["query"])
        self.assertEqual(error.exception.status_code, 503)
        self.assertNotIn("secret", error.exception.detail)

    async def test_missing_attachment_never_accesses_storage(self):
        db = self.database()
        db.scalar.return_value = None
        with patch.object(data, "S3Client") as storage:
            with self.assertRaises(HTTPException) as error:
                await data.media(99, False, db)
        self.assertEqual(error.exception.status_code, 404)
        storage.assert_not_called()
