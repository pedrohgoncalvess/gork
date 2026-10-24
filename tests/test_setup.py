from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from cryptography.fernet import Fernet
from dotenv import dotenv_values

from api.admin.schemas import SyncInput, TestSettings
from api.admin import synchronization as sync
from scripts.setup import prepare
from services import setup


class SetupValidationTests(unittest.TestCase):
    def test_test_mode_requires_a_valid_number(self):
        for data in ({"test_mode": True}, {"test_number": "not-a-phone"}):
            with self.assertRaises(ValidationError):
                TestSettings(**data)
        self.assertEqual(TestSettings(test_mode=True, test_number="+5511999999999").test_number, "+5511999999999")

    def test_every_preset_and_calendar_months(self):
        now = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)
        for period, days in (("3d", 3), ("5d", 5), ("1w", 7), ("2w", 14)):
            start, end = sync.time_window(SyncInput(history=True, period=period), now)
            self.assertEqual((end-start).days, days)
        self.assertEqual(sync.time_window(SyncInput(period="1m"), now)[0].day, 28)
        self.assertEqual(sync.time_window(SyncInput(period="3m"), now)[0].year, 2025)
        self.assertIsNone(sync.time_window(SyncInput(period="all"), now)[0])

    def test_custom_window_requires_ordered_dates_and_timezone(self):
        for start, end in ((None, None), ("2026-01-01", "2026-02-01"),
                           ("2026-02-01T00:00:00Z", "2026-01-01T00:00:00Z")):
            with self.assertRaises(ValidationError):
                SyncInput(period="custom", start=start, end=end)
        data = SyncInput(period="custom", start="2026-01-01T00:00:00-03:00", end="2026-02-01T00:00:00-03:00")
        self.assertEqual(sync.time_window(data), (data.start, data.end))
        with self.assertRaises(ValidationError):
            SyncInput(contacts=False, history=False)

    def test_setup_preserves_credentials_and_is_idempotent(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text("OPENROUTER_KEY=keep-me\nADMIN_PASSWORD=already-set\n", encoding="utf-8")
            generated = prepare(root)
            self.assertNotIn("ADMIN_PASSWORD", generated)
            Fernet(generated["MCP_ENCRYPTION_KEY"])
            content = (root / ".env").read_text(encoding="utf-8")
            self.assertEqual(prepare(root), {})
            self.assertEqual((root / ".env").read_text(encoding="utf-8"), content)
            self.assertEqual(dotenv_values(root / ".env")["OPENROUTER_KEY"], "keep-me")


class SetupAsyncTests(unittest.IsolatedAsyncioTestCase):
    def database(self, db):
        @asynccontextmanager
        async def context():
            yield db
        return context

    async def test_principal_reuses_user_and_maps_phone_and_lid(self):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        with (patch.object(setup, "PgConnection", self.database(db)),
              patch.object(setup, "UserRepository") as repo,
              patch.object(setup, "request", new=AsyncMock(return_value={"lid": "987@lid"}))):
            repo.return_value.find_or_create = AsyncMock(return_value=SimpleNamespace(id=42))
            mapped = await setup.map_principal({"id": "5511999999999:3@c.us", "pushName": "Gork"})
        self.assertEqual(mapped, {"user_id": 42, "phone_number": "5511999999999", "lid": "987"})
        repo.return_value.find_or_create.assert_awaited_once_with(lid="987", phone_number="5511999999999", name="Gork")

    async def test_pagination_continues_after_short_page(self):
        with patch.object(sync, "request", new=AsyncMock(side_effect=[[{"id": "a"}], [{"id": "b"}], []])) as request:
            batches = [batch async for batch in sync.pages("/messages", {})]
        self.assertEqual(len(batches), 2)
        self.assertEqual([call.kwargs["params"]["offset"] for call in request.await_args_list], [0, 100, 200])

    async def test_repeated_pages_fail_instead_of_looping(self):
        with patch.object(sync, "request", new=AsyncMock(return_value=[{"id": "a"}])):
            with self.assertRaisesRegex(RuntimeError, "pagination"):
                _ = [batch async for batch in sync.pages("/messages", {})]

    async def test_contacts_finish_after_321_entries_without_requesting_invalid_offset(self):
        batches = [[{"id": str(i)} for i in range(start, end)]
                   for start, end in ((0, 101), (100, 201), (200, 301), (300, 321))]
        with patch.object(sync, "request", new=AsyncMock(side_effect=batches)) as request:
            received = [batch async for batch in sync.pages("/api/contacts/all", {}, stop_on_short_page=True)]
        self.assertEqual(sum(map(len, received)), 321)
        self.assertEqual([call.kwargs["params"]["offset"] for call in request.await_args_list], [0, 100, 200, 300])

    async def test_exactly_100_contacts_does_not_request_an_out_of_range_page(self):
        batch = [{"id": str(i)} for i in range(100)]
        with patch.object(sync, "request", new=AsyncMock(side_effect=[batch])) as request:
            received = [page async for page in sync.pages("/contacts", {}, stop_on_short_page=True)]
        self.assertEqual(sum(map(len, received)), 100)
        request.assert_awaited_once()

    async def test_last_contacts_page_transitions_to_history_and_completes(self):
        seen = []
        async def pages(path, params, **kwargs):
            seen.append(path)
            if path == "/api/contacts/all":
                self.assertTrue(kwargs["stop_on_short_page"])
                yield [{"id": "5511999999999@c.us"}]
            else:
                yield [{"id": "message", "timestamp": datetime.now(timezone.utc).timestamp() - 30}]
        with (patch.object(sync, "pages", pages),
              patch.object(sync, "PgConnection", self.database(Mock())),
              patch.object(sync, "contact_user", new=AsyncMock(return_value=Mock())),
              patch.object(sync, "import_message", new=AsyncMock(return_value=True)),
              patch.object(sync, "progress", new=AsyncMock()) as progress):
            await sync.run("job", SyncInput(contacts=True, history=True), {"user_id": 1})
        self.assertEqual(len(seen), 2)
        self.assertEqual(progress.await_args_list[1].kwargs["phase"], "history")
        self.assertEqual(progress.await_args.args[1], {"contacts": 1, "messages": 1, "skipped": 0})
        self.assertEqual(progress.await_args.args[2], "completed")

    async def test_history_insert_is_idempotent_and_private_chat_scoped(self):
        result = Mock()
        result.scalar_one_or_none.return_value = 7
        db = SimpleNamespace(execute=AsyncMock(return_value=result), commit=AsyncMock())
        payload = {"id": "true_5511888888888@c.us_OLD", "fromMe": True,
                   "to": "5511888888888@c.us", "timestamp": 1700000000, "body": "!image old command"}
        with (patch.object(sync, "PgConnection", self.database(db)),
              patch.object(sync, "contact_user", new=AsyncMock(return_value=SimpleNamespace(id=5))),
              patch.object(sync, "save_reference", new=AsyncMock())):
            self.assertTrue(await sync.import_message(payload, {"user_id": 42}))
        stmt = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
        self.assertIn("ON CONFLICT (message_id) DO NOTHING", str(stmt))
        self.assertEqual(stmt.params["user_id"], 42)
        self.assertEqual(stmt.params["chat_user_id"], 5)

    async def test_private_history_uses_only_incoming_contact_name(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock()), commit=AsyncMock())
        for outgoing in (False, True):
            payload = {"id": f"{str(outgoing).lower()}_5511888888888@c.us_OLD",
                       "fromMe": outgoing, "from": "5511888888888@c.us",
                       "to": "5511888888888@c.us", "timestamp": 1700000000,
                       "body": "oi", "pushName": "Ana"}
            with (self.subTest(outgoing=outgoing),
                  patch.object(sync, "PgConnection", self.database(db)),
                  patch.object(sync, "contact_user", new=AsyncMock(return_value=SimpleNamespace(id=5))) as contact,
                  patch.object(sync, "save_reference", new=AsyncMock())):
                await sync.import_message(payload, {"user_id": 42})
                self.assertEqual(contact.await_args.kwargs['name'], None if outgoing else 'Ana')

    async def test_group_history_resolves_missing_group_name(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=Mock()), commit=AsyncMock())
        groups = SimpleNamespace(find_or_create=AsyncMock(side_effect=[
            SimpleNamespace(id=3, name=None), SimpleNamespace(id=3, name="Amigos")]))
        payload = {"id": "true_120363123456789012@g.us_OLD", "fromMe": True,
                   "to": "120363123456789012@g.us", "timestamp": 1700000000, "body": "oi"}
        with (patch.object(sync, "PgConnection", self.database(db)),
              patch.object(sync, "GroupRepository", return_value=groups),
              patch.object(sync, "get_group_info", new=AsyncMock(return_value={"subject": "Amigos", "desc": "Grupo"})) as info,
              patch.object(sync, "save_reference", new=AsyncMock())):
            await sync.import_message(payload, {"user_id": 42})
        info.assert_awaited_once_with("120363123456789012@g.us")
        self.assertEqual(groups.find_or_create.await_args.kwargs['name'], 'Amigos')

    async def test_test_number_is_normalized_and_saved(self):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        with (patch.object(setup, "settings", new=AsyncMock(return_value={})),
              patch("services.ban_cache.invalidate", new=AsyncMock())):
            await setup.save_test_settings(True, "+5511999999999", db)
        from security.crypto import decrypt
        saved = db.execute.await_args.args[1]
        self.assertTrue(saved['mode'])
        self.assertNotEqual(saved['number'], '5511999999999')
        self.assertEqual(decrypt(saved['number'], 'identity'), '5511999999999')

    async def test_test_mode_dispatches_only_the_selected_private_contact(self):
        from api.routes.webhook.waha import services
        for remote, expected in (("5511999999999@s.whatsapp.net", 1),
                                 ("5521888888888@s.whatsapp.net", 0), ("120363123456789012@g.us", 0)):
            body = {"event": "messages.upsert", "data": {"key": {"remoteJid": remote}}}
            with (patch.object(services, "PgConnection", self.database(Mock())),
                  patch.object(services, "serialize_direct_message", lambda _: self.database(None)()),
                  patch.object(services, "settings", new=AsyncMock(return_value={"test_mode": True, "test_number": "5511999999999"})),
                  patch.object(services, "process_private_message", new=AsyncMock()) as private,
                  patch.object(services, "process_group_message", new=AsyncMock()) as group):
                await services.process_webhook(body, Mock())
            self.assertEqual(private.await_count, expected)
            group.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
