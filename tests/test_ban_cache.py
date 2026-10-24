from security.crypto import encrypt, decrypt
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from contextlib import asynccontextmanager
from types import SimpleNamespace

from services import ban_cache as cache
from services import group_ban
from api.routes.webhook.waha import services
from api.routes.webhook.waha.normalize import normalize_webhook
from tests.test_waha import event


class BanCacheTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self, **changes):
        value = {'test_mode': False, 'bans': [{'chat': '123@g.us', 'aliases': ['222@lid','5522@c.us'],
                 'started': int(time.time()) - 20, 'until': time.time() + 100}]}
        return {**value, **changes}

    def data(self):
        return {'key': {'participant': '222@lid', 'id': 'MSG', 'remoteJid': '123@g.us'},
                'messageTimestamp': int(time.time())}

    async def test_warm_cache_checks_members_without_database(self):
        redis = SimpleNamespace(get=AsyncMock(return_value=encrypt(json.dumps(self.snapshot()), "ban.cache")))
        with (patch.object(cache, 'client', return_value=redis), patch.object(cache, 'PgConnection') as db):
            self.assertTrue(await cache.decision(self.data(), '123@g.us'))
            self.assertFalse(await cache.decision(self.data(), '456@g.us'))
        db.assert_not_called()

    async def test_expiry_test_mode_and_older_messages_do_not_delete(self):
        state = self.snapshot()
        state['bans'][0]['until'] = time.time() - 1
        for value in (state, self.snapshot(test_mode=True)):
            with patch.object(cache, 'snapshot', AsyncMock(return_value=value)):
                self.assertFalse(await cache.decision(self.data(), '123@g.us'))
        data = self.data()
        data['messageTimestamp'] -= 100
        with patch.object(cache, 'snapshot', AsyncMock(return_value=self.snapshot())):
            self.assertFalse(await cache.decision(data, '123@g.us'))

    async def test_redis_failure_requests_database_fallback(self):
        from redis.exceptions import ConnectionError
        redis = SimpleNamespace(get=AsyncMock(side_effect=ConnectionError('offline')))
        with patch.object(cache, 'client', return_value=redis):
            self.assertIsNone(await cache.decision(self.data(), '123@g.us'))

    async def test_cache_hit_sends_delete_before_any_database_work(self):
        data = self.data()
        with (patch.object(services, 'cached_ban_decision', AsyncMock(return_value=True)),
              patch.object(services, 'settings', AsyncMock()) as settings,
              patch.object(group_ban, 'PgConnection') as database,
              patch.object(group_ban, 'request', AsyncMock()) as request):
            self.assertTrue(await services.moderate_group_message({'data': data}))
        settings.assert_not_awaited()
        database.assert_not_called()
        self.assertEqual(request.await_args.args[0], 'DELETE')

    async def test_audit_occurs_after_delete_without_running_normal_handlers(self):
        order = []
        async def delete(_):
            order.append('delete')
            return True
        async def audit(*_):
            order.append('database')
        with (patch.object(services, 'moderate_group_message', side_effect=delete),
              patch.object(services, 'persist_ban_deletion', side_effect=audit),
              patch.object(services, 'process_webhook', AsyncMock()) as process):
            await services.process_waha_webhook(event(), Mock())
        self.assertEqual(order, ['delete', 'database'])
        process.assert_not_awaited()

    async def test_audit_preserves_received_message_and_is_idempotent(self):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        @asynccontextmanager
        async def connection():
            yield db
        body = event(body='texto excluído', media={'mimetype': 'audio/ogg', 'url': 'http://waha/file'})
        with (patch.object(services, 'PgConnection', connection),
              patch.object(services, 'save_reference', AsyncMock()) as reference):
            await services.persist_ban_deletion(body, normalize_webhook(body))
        sql, params = db.execute.await_args.args
        self.assertEqual(json.loads(params['payload'])['body'], 'texto excluído')
        self.assertIn('ON CONFLICT', str(sql))
        reference.assert_awaited_once()

    async def test_invalidation_advances_generation_and_removes_snapshot_atomically(self):
        redis = SimpleNamespace(eval=AsyncMock())
        with patch.object(cache, 'client', return_value=redis):
            await cache.invalidate()
        script = redis.eval.await_args.args[0]
        self.assertIn("'INCR'", script)
        self.assertIn("'DEL'", script)

    async def test_concurrent_revoke_prevents_publishing_old_database_snapshot(self):
        mode = Mock()
        mode.scalar_one.return_value = False
        rows = Mock()
        rows.mappings.return_value.all.return_value = []
        db = SimpleNamespace(execute=AsyncMock(side_effect=[mode, rows]))
        @asynccontextmanager
        async def connection():
            yield db
        redis = SimpleNamespace(get=AsyncMock(side_effect=[None, '1']), eval=AsyncMock(return_value=0))
        with (patch.object(cache, 'client', return_value=redis), patch.object(cache, 'PgConnection', connection)):
            self.assertIsNone(await cache.snapshot())
        self.assertIn('~= ARGV[1]', redis.eval.await_args.args[0])

    async def test_cache_miss_publishes_active_bans_with_their_expiry(self):
        mode = Mock()
        mode.scalar_one.return_value = False
        rows = Mock()
        rows.mappings.return_value.all.return_value = [{'chat_id': '123@g.us', 'target_aliases': ['222@lid'],
            'started': 1800000000, 'expires_at': 1800001800}]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[mode, rows]))
        @asynccontextmanager
        async def connection():
            yield db
        redis = SimpleNamespace(get=AsyncMock(side_effect=[None, '2']), eval=AsyncMock(return_value=1))
        with (patch.object(cache, 'client', return_value=redis), patch.object(cache, 'PgConnection', connection)):
            state = await cache.snapshot()
        self.assertEqual(state['bans'][0]['until'], 1800001800)
        self.assertEqual(state['bans'][0]['aliases'], ['222@lid'])
        sealed = redis.eval.await_args.args[-1]
        self.assertNotIn('5522@c.us', sealed)
        self.assertEqual(json.loads(decrypt(sealed, 'ban.cache')), state)
