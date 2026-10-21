import base64
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import httpx
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from api.admin import connection, store
from api.admin.auth import COOKIE_NAME, create_session, csrf_token
from api.admin.router import STATIC_DIR, get_db, router
from api.admin.schemas import AgentInput, BlacklistInput, CommandInput, OverrideInput, PairingCode, UserInput
from database.models.base import User, WhiteList
from database.models.manager import Agent, Model
from database.operations.manager.agent import AgentRepository


class AdminAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"ADMIN_PASSWORD": "test-only-password", "ADMIN_SESSION_SECRET": "test-only-secret"})
        self.env.start()
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.mount("/admin/assets", StaticFiles(directory=STATIC_DIR))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()

    async def login(self):
        response = await self.client.post("/admin/api/login", json={"password": "test-only-password"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertIn("Path=/admin", response.headers["set-cookie"])
        return response.json()["csrf_token"]

    async def test_page_and_assets_serve_from_same_application(self):
        response = await self.client.get("/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("sidebar", response.text)
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        for path in ("app.js", "app.css", "tokens.css", "mark.svg"):
            self.assertEqual((await self.client.get("/admin/assets/" + path)).status_code, 200)

    async def test_all_management_endpoints_require_authentication(self):
        for path in ("connection", "overview", "directory/user", "directory/group", "blacklist", "agents", "models", "commands", "overrides", "settings", "sync", "data/attachments", "data/messages", "media/1", "bans"):
            with self.subTest(path=path):
                self.assertEqual((await self.client.get("/admin/api/" + path)).status_code, 401)

    async def test_login_uses_httponly_strict_cookie_without_provider_secrets(self):
        csrf = await self.login()
        self.assertTrue(csrf)
        response = await self.client.get("/admin/api/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["csrf_token"], csrf)
        self.assertNotIn("test-only-password", response.text)
        self.assertNotIn("test-only-secret", response.text)

    async def test_wrong_password_and_cross_origin_login_fail(self):
        self.assertEqual((await self.client.post("/admin/api/login", json={"password": "wrong"})).status_code, 401)
        response = await self.client.post("/admin/api/login", json={"password": "test-only-password"}, headers={"Origin": "https://other.test"})
        self.assertEqual(response.status_code, 403)

    async def test_disabled_panel_does_not_accept_empty_password(self):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": ""}):
            response = await self.client.post("/admin/api/login", json={"password": "anything"})
        self.assertEqual(response.status_code, 503)

    async def test_mutations_require_csrf_even_with_authenticated_cookie(self):
        await self.login()
        with patch("api.admin.connection.start_connection", new=AsyncMock()) as start:
            response = await self.client.post("/admin/api/connection/start")
        self.assertEqual(response.status_code, 403)
        start.assert_not_awaited()

    async def test_connection_start_uses_existing_session_helper(self):
        csrf = await self.login()
        with patch("api.admin.connection.start_connection", new=AsyncMock(return_value={"status": "SCAN_QR_CODE"})) as start:
            response = await self.client.post("/admin/api/connection/start", headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.json()["status"], "SCAN_QR_CODE")
        start.assert_awaited_once()

    async def test_logout_and_password_change_invalidate_sessions(self):
        csrf = await self.login()
        saved = self.client.cookies.get(COOKIE_NAME)
        self.assertEqual((await self.client.post("/admin/api/logout", headers={"X-CSRF-Token": csrf})).status_code, 200)
        self.assertEqual((await self.client.get("/admin/api/session")).status_code, 401)
        self.client.cookies.set(COOKIE_NAME, saved, domain="test.local", path="/admin")
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "changed-password"}):
            self.assertEqual((await self.client.get("/admin/api/session")).status_code, 401)

    async def test_cookie_tampering_is_rejected(self):
        session = create_session()
        self.client.cookies.set(COOKIE_NAME, session[:-1] + ("0" if session[-1]!="0" else "1"), path="/admin")
        self.assertEqual((await self.client.get("/admin/api/session")).status_code, 401)

    async def test_pairing_validates_phone_before_upstream_request(self):
        csrf = await self.login()
        with patch("api.admin.connection.pairing_code", new=AsyncMock()) as pairing:
            response = await self.client.post("/admin/api/connection/code", json={"phone_number": "invalid"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.status_code, 422)
        pairing.assert_not_awaited()

    async def test_pairing_code_is_exposed_only_to_authenticated_admin(self):
        csrf = await self.login()
        with patch("api.admin.connection.pairing_code", new=AsyncMock(return_value={"code": "ABCD-1234"})) as pairing:
            response = await self.client.post("/admin/api/connection/code", json={"phone_number": "5511999999999"}, headers={"X-CSRF-Token": csrf})
        self.assertEqual(response.json(), {"code": "ABCD-1234"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        pairing.assert_awaited_once_with("5511999999999")


class AdminConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_excludes_waha_config_and_keys(self):
        with (patch("api.admin.connection.request", new=AsyncMock(return_value={"status": "WORKING", "config": {"secret": "hidden"}, "me": {"id": "5511@c.us", "pushName": "Gork"}})),
              patch("services.setup.map_principal", new=AsyncMock(return_value={"user_id": 1, "phone_number": "5511", "lid": "123"})) as mapping):
            result = await connection.connection_status()
        mapping.assert_awaited_once_with({"id": "5511@c.us", "pushName": "Gork"})
        self.assertEqual(result["principal"]["user_id"], 1)
        self.assertEqual(result["status"], "WORKING")
        self.assertNotIn("config", result)
        self.assertEqual(result["me"]["name"], "Gork")

    async def test_absent_session_is_not_created_by_status_poll(self):
        error = httpx.HTTPStatusError("missing", request=httpx.Request("GET", "http://waha"), response=httpx.Response(404))
        with patch("api.admin.connection.request", new=AsyncMock(side_effect=error)) as request:
            result = await connection.connection_status()
        self.assertEqual(result["status"], "NOT_CREATED")
        self.assertEqual(request.await_count, 1)

    async def test_pairing_strips_plus_and_passes_correct_waha_contract(self):
        with (patch("api.admin.connection.ensure_pairing_ready", new=AsyncMock()),
              patch("api.admin.connection.request", new=AsyncMock(return_value={"code": "ABCD-EFGH"})) as request):
            result = await connection.pairing_code("+5511999999999")
        self.assertEqual(result, {"code": "ABCD-EFGH"})
        self.assertTrue(request.await_args.args[1].endswith("/auth/request-code"))
        self.assertEqual(request.await_args.kwargs["payload"], {"phoneNumber": "5511999999999"})

    async def test_upstream_failure_is_sanitized(self):
        from fastapi import HTTPException
        error = httpx.HTTPStatusError("secret upstream URL", request=httpx.Request("POST", "http://waha"), response=httpx.Response(500, text="private key"))
        with (patch("api.admin.connection.ensure_pairing_ready", new=AsyncMock()),
              patch("api.admin.connection.request", new=AsyncMock(side_effect=error))):
            with self.assertRaises(HTTPException) as failure:
                await connection.pairing_code("5511999999999")
        self.assertEqual(failure.exception.status_code, 502)
        self.assertNotIn("private key", failure.exception.detail)

    async def test_pairing_starts_stopped_session_and_waits_until_ready(self):
        with (patch("api.admin.connection.connection_status", new=AsyncMock(side_effect=[{"status": "STOPPED"}, {"status": "SCAN_QR_CODE"}])),
              patch("api.admin.connection.start_connection", new=AsyncMock(return_value={"status": "STARTING"})) as start,
              patch("api.admin.connection.asyncio.sleep", new=AsyncMock())):
            await connection.ensure_pairing_ready()
        start.assert_awaited_once()


class AdminStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_whitelist_uses_real_sender_identity_and_updates_existing_entry(self):
        entry = WhiteList(id=10, sender_type="user", sender_id=2, is_admin=False)
        duplicate = WhiteList(id=11, sender_type="user", sender_id=2, is_admin=False)
        result = Mock()
        result.scalars.return_value.all.return_value = [entry, duplicate]
        db = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock())
        with patch("api.admin.store.get_entity", new=AsyncMock()) as lookup:
            saved = await store.set_whitelist(db, "user", 2, True, True)
        lookup.assert_awaited_once_with(db, User, 2, lock=True)
        self.assertTrue(entry.is_admin)
        self.assertIsNotNone(duplicate.deleted_at)
        self.assertEqual(saved, {"allowed": True, "is_admin": True})
        db.commit.assert_awaited_once()

    async def test_removing_whitelist_soft_deletes_all_active_rows(self):
        entries = [WhiteList(id=10), WhiteList(id=11)]
        result = Mock()
        result.scalars.return_value.all.return_value = entries
        db = SimpleNamespace(execute=AsyncMock(return_value=result), add=Mock(), commit=AsyncMock())
        with patch("api.admin.store.get_entity", new=AsyncMock()):
            await store.set_whitelist(db, "group", 2, False, True)
        self.assertTrue(all(item.deleted_at for item in entries))
        db.add.assert_not_called()

    async def test_blacklist_saves_feature_scope_with_existing_runtime_aliases(self):
        db = SimpleNamespace(commit=AsyncMock(), add=Mock())
        existing = SimpleNamespace(features=[])
        with (patch("api.admin.store.get_entity", new=AsyncMock()),
              patch("api.admin.store.BlackListRepository") as repo):
            repo.normalize_feature.side_effect=lambda value: {"send_audio":"audio"}.get(value,value)
            repo.return_value.get_active=AsyncMock(return_value=existing)
            result=await store.save_blacklist(db, BlacklistInput(user_id=3,features=["send_audio", "image"]))
        self.assertEqual(existing.features,["audio","image"])
        self.assertEqual(result["user_id"],3)

    async def test_agent_model_selection_is_marked_persistent(self):
        agent=SimpleNamespace(id=4,model_id=2,model_managed=False,prompt_managed=False,prompt="old")
        db=SimpleNamespace(commit=AsyncMock())
        with patch("api.admin.store.get_entity",new=AsyncMock(side_effect=[agent,Model(id=8)])):
            await store.save_agent(db,4,AgentInput(model_id=8))
        self.assertEqual(agent.model_id,8)
        self.assertTrue(agent.model_managed)
        self.assertFalse(agent.prompt_managed)
        self.assertEqual(agent.prompt,"old")

    async def test_startup_preserves_admin_model_and_prompt_but_refreshes_schema(self):
        repo=AgentRepository(Mock())
        existing=SimpleNamespace(id=4,model_managed=True,prompt_managed=True)
        with (patch.object(repo,"find_by_name",new=AsyncMock(return_value=existing)),
              patch.object(repo,"update",new=AsyncMock()) as update):
            await repo.upsert_by_name("conversation-dm","file prompt",99,"schema")
        update.assert_awaited_once_with(4,{"response_format":"schema"})

    async def test_unmanaged_agents_still_follow_project_configuration(self):
        repo=AgentRepository(Mock())
        existing=SimpleNamespace(id=4,model_managed=False,prompt_managed=False)
        with (patch.object(repo,"find_by_name",new=AsyncMock(return_value=existing)),
              patch.object(repo,"update",new=AsyncMock()) as update):
            await repo.upsert_by_name("conversation-dm","new prompt",99,"schema")
        update.assert_awaited_once_with(4,{"response_format":"schema","prompt":"new prompt","model_id":99})

    async def test_remove_override_cannot_resurrect_older_rows_or_affect_other_scopes(self):
        item=SimpleNamespace(agent_id=2,user_id=4,group_id=None)
        db=SimpleNamespace(execute=AsyncMock(),commit=AsyncMock())
        with patch("api.admin.store.get_entity",new=AsyncMock(side_effect=[item,Mock()])):
            await store.remove_override(db,1)
        sql=str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect(),compile_kwargs={"literal_binds":True}))
        self.assertIn("agent_id = 2",sql)
        self.assertIn("user_id = 4",sql)
        self.assertIn("group_id IS NULL",sql)

    async def test_command_rule_saves_scope_expiry_and_message(self):
        db=SimpleNamespace(add=Mock(),commit=AsyncMock())
        expiry=datetime.now(timezone.utc)+timedelta(days=1)
        with patch("api.admin.store.get_entity",new=AsyncMock()):
            await store.save_command(db,CommandInput(command="!image",user_id=2,group_id=7,message="indisponível",disabled_until=expiry))
        item=db.add.call_args.args[0]
        self.assertEqual((item.command,item.user_id,item.group_id,item.message),("image",2,7,"indisponível"))
        self.assertEqual(item.disabled_until,expiry)


class AdminValidationTests(unittest.TestCase):
    def test_model_override_requires_exactly_one_conversation(self):
        for changes in ({},{"user_id":1,"group_id":2}):
            with self.assertRaises(ValidationError):OverrideInput(agent_id=1,model_id=2,**changes)

    def test_command_expiry_rejects_past_or_naive_timestamps(self):
        for value in (datetime.now()-timedelta(days=1),datetime.now(timezone.utc)-timedelta(minutes=1)):
            with self.assertRaises(ValidationError):CommandInput(command="image",disabled_until=value)

    def test_user_needs_a_valid_identity(self):
        with self.assertRaises(ValidationError):UserInput(name="Ana")
        with self.assertRaises(ValidationError):UserInput(name="Ana",phone_number="not-a-number")
        self.assertEqual(UserInput(name="Ana",lid="12345678@lid").lid,"12345678@lid")

    def test_unknown_command_is_not_saved_as_silent_nonfunctional_rule(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):store.valid_command("invented-command")
        self.assertEqual(store.valid_command("!image"),"image")


if __name__ == "__main__":
    unittest.main()
