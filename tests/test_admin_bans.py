from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from api.admin.dependencies import get_db
from tests import test_admin as admin_tests


class AdminBanTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = admin_tests.AdminAuthTests.asyncSetUp
    asyncTearDown = admin_tests.AdminAuthTests.asyncTearDown
    login = admin_tests.AdminAuthTests.login

    def database(self, results):
        db = SimpleNamespace(execute=AsyncMock(side_effect=results), commit=AsyncMock())
        async def dependency():
            yield db
        self.app.dependency_overrides[get_db] = dependency
        return db

    def result(self, scalar=None, rows=None):
        value = Mock()
        value.scalar_one.return_value = scalar
        value.scalar_one_or_none.return_value = scalar
        value.mappings.return_value.all.return_value = rows or []
        return value

    async def test_lists_names_tallies_deadlines_and_filters(self):
        await self.login()
        now = datetime.now(timezone.utc)
        row = {'id': 1, 'target_name': 'Ana', 'group_name': 'Equipe', 'status': 'active',
               'yes_votes': 6, 'no_votes': 1, 'opened_at': now, 'closes_at': now,
               'ban_started_at': now, 'ban_until': now, 'next_vote_at': now}
        db = self.database([self.result(scalar=1), self.result(rows=[row])])
        response = await self.client.get('/admin/api/bans?view=active&q=Ana&offset=30&limit=30')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.json()['items'][0]['yes_votes'], 6)
        self.assertEqual(response.json()['items'][0]['ban_until'], now.isoformat())
        self.assertEqual(response.json()['items'][0]['next_vote_at'], now.isoformat())
        sql, params = db.execute.await_args.args
        self.assertEqual(params['view'], 'active')
        self.assertEqual(params['search'], '%Ana%')
        self.assertEqual(params['offset'], 30)
        self.assertIn('p.session=:session', str(sql))
        self.assertIn("p.ban_until > clock_timestamp()", str(sql))

    async def test_filter_and_pagination_validation(self):
        await self.login()
        db = self.database([])
        for query in ('view=unknown', 'offset=-1', 'limit=101'):
            self.assertEqual((await self.client.get('/admin/api/bans?' + query)).status_code, 422)
        db.execute.assert_not_awaited()

    async def test_management_requires_authentication_and_csrf(self):
        db = self.database([])
        for action in ('cancel', 'revoke'):
            self.assertEqual((await self.client.post(f'/admin/api/bans/1/{action}')).status_code, 401)
        await self.login()
        for action in ('cancel', 'revoke'):
            self.assertEqual((await self.client.post(f'/admin/api/bans/1/{action}')).status_code, 403)
        db.execute.assert_not_awaited()

    async def test_cancel_only_pending_polls_and_revoke_only_live_bans(self):
        csrf = await self.login()
        for action, status, condition in [('cancel', 'cancelled', "status IN ('creating','open')"),
                                           ('revoke', 'revoked', "ban_until > clock_timestamp()")]:
            db = self.database([self.result(scalar=1)])
            response = await self.client.post(f'/admin/api/bans/1/{action}', headers={'X-CSRF-Token': csrf})
            self.assertEqual(response.status_code, 200)
            sql, params = db.execute.await_args.args
            self.assertEqual(params['status'], status)
            self.assertIn(condition, str(sql))
            self.assertIn('session=:session', str(sql))
            self.assertIn('notice_sent=TRUE', str(sql))
            self.assertIn('finished_at=COALESCE', str(sql))
            db.commit.assert_awaited_once()

    async def test_missing_and_concurrently_changed_records(self):
        csrf = await self.login()
        for exists, code in [(None, 404), (1, 409)]:
            for action in ('cancel', 'revoke'):
                db = self.database([self.result(), self.result(scalar=exists)])
                response = await self.client.post(f'/admin/api/bans/1/{action}', headers={'X-CSRF-Token': csrf})
                self.assertEqual(response.status_code, code)
                db.commit.assert_not_awaited()
