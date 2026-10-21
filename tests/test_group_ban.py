import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from services import group_ban as ban
from tests import test_waha as waha_tests


class BanRulesTests(unittest.TestCase):
    def test_expiration_defaults_limits_and_both_separators(self):
        self.assertEqual(ban.expiration_minutes('!ban @123 :time 3hr'), 10)
        for minutes in (5, 10, 20):
            for separator in (' ', '='):
                command = f'!ban @123 :expiration{separator}{minutes} :time 30min'
                self.assertEqual(ban.expiration_minutes(command), minutes)
                self.assertEqual(ban.duration_minutes(command), 30)

    def test_expiration_rejects_invalid_out_of_range_and_duplicate_values(self):
        for value in ('', '0', '4', '21', '-5', '5.5', 'abc', '1:30', '5min'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ban.expiration_minutes('!ban @123 :expiration ' + value)
        with self.assertRaises(ValueError):
            ban.expiration_minutes('!ban @123 :expiration 5 :expiration=20')

    def test_duration_formats_default_and_boundaries(self):
        for value, expected in [(None, 30), ('3hr', 180), ('30min', 30), ('120', 120),
                                ('1:30', 90), ('00:30', 30), ('3:00', 180), ('1', 1)]:
            for separator in (' ', '='):
                command = '!ban @123' + (f' :time{separator}{value}' if value else '')
                self.assertEqual(ban.duration_minutes(command), expected)

    def test_rejects_zero_over_limit_and_malformed_times(self):
        for value in ('0', '-1', '181', '4hr', '3:01', '1:60', '1:3', 'abc', '1.5hr', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ban.duration_minutes('!ban @123 :time ' + value)
        with self.assertRaises(ValueError):
            ban.duration_minutes('!ban @123 :time 30 :time 40')

    def test_third_of_humans_minimum_three_and_majority_of_cast_votes(self):
        self.assertEqual(ban.quorum(10), 4)
        self.assertEqual(ban.quorum(9), 3)
        self.assertEqual(ban.quorum(2), 3)
        self.assertTrue(ban.approved(3, 10, 4))
        self.assertFalse(ban.approved(3, 10, 3))
        self.assertFalse(ban.approved(2, 10, 4))
        self.assertFalse(ban.approved(2, 5, 2))
        self.assertTrue(ban.approved(2, 5, 3))
        self.assertFalse(ban.approved(0, 0, 0))

    def test_phone_and_lid_are_one_voter(self):
        members = [{'id': '123@lid', 'pn': '5511@s.whatsapp.net'}, {'id': '999@c.us'}]
        voters = ban.electorate(members)
        self.assertEqual(voters['123@lid'], voters['5511@c.us'])
        self.assertEqual(len(set(voters.values())), 2)


class BanFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        availability = patch.object(ban, 'check_ban_availability', AsyncMock(return_value=None))
        self.availability = availability.start()
        self.addCleanup(availability.stop)
        hooks = patch.object(ban, 'ensure_ban_webhooks', AsyncMock())
        hooks.start()
        self.addCleanup(hooks.stop)
        logs = patch.object(ban.logger, 'info', AsyncMock())
        logs.start()
        self.addCleanup(logs.stop)
        cache = patch.object(ban, 'invalidate_ban_cache', AsyncMock())
        cache.start()
        self.addCleanup(cache.stop)

    def database(self, db):
        @asynccontextmanager
        async def connection():
            yield db
        return connection

    def result(self, row=None, scalar=None, rows=None, tally=None):
        result = Mock()
        result.mappings.return_value.first.return_value = row
        result.mappings.return_value.all.return_value = rows or []
        result.mappings.return_value.one.return_value = tally or {'yes': 0, 'voted': 0}
        result.first.return_value = row
        result.scalar_one_or_none.return_value = scalar
        result.scalar_one.return_value = scalar
        return result

    async def test_non_admin_does_not_publish_poll(self):
        members = [{'id': '111@lid', 'pn': '5511@c.us', 'role': 'participant'}]
        with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
              patch.object(ban, 'bot_aliases', AsyncMock(return_value={'5511@c.us'})),
              patch.object(ban, 'send_message', AsyncMock()) as send,
              patch.object(ban, 'request', AsyncMock()) as request):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', {})
        request.assert_not_awaited()
        self.assertEqual(send.await_args.args[1], ban.ADMIN_REQUIRED)

    async def test_private_chat_rejected(self):
        with (patch.object(ban, 'participants', AsyncMock()) as members,
              patch.object(ban, 'send_message', AsyncMock()) as send):
            await ban.handle_ban_command('123@c.us', '!ban @222', 'CMD', {})
        members.assert_not_awaited()
        self.assertIn('só funciona em grupos', send.await_args.args[1])

    async def test_admin_sends_poll_and_short_notice_with_each_member_mentioned(self):
        members = [{'id': '111@lid', 'pn': '5511@c.us', 'role': 'admin'},
                   {'id': '222@lid', 'pn': '5522@c.us', 'role': 'participant'},
                   {'id': '333@lid', 'pn': '5533@c.us', 'role': 'participant'}]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(scalar='Ana'),
                              self.result(scalar=7), self.result(scalar=7)]), commit=AsyncMock())
        body = {'data': {'contextInfo': {'mentionedJid': ['111@lid', '5522@s.whatsapp.net']}}}
        with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
              patch.object(ban, 'bot_aliases', AsyncMock(return_value={'5511@c.us'})),
              patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'send_message', AsyncMock()) as send,
              patch.object(ban, 'request', AsyncMock(return_value={'id': 'true_123@g.us_POLL'})) as request):
            await ban.handle_ban_command('123@g.us', '@Gork !ban @5522 :time 1:30', 'CMD', body)
        poll = request.await_args.kwargs['payload']['poll']
        self.assertEqual(poll, {'name': 'Banimento Ana', 'options': ['Sim', 'Não'], 'multipleAnswers': False})
        self.assertEqual(send.await_args.kwargs['mentioned'], ['222@lid', '333@lid'])
        self.assertEqual(send.await_args.args[1],
                         'Votação para banimento de Ana.\nExpira em 10 minutos.\n\n@222 @333')
        self.assertEqual(db.execute.await_args_list[1].args[1]['duration'], 90)
        self.assertEqual(db.execute.await_args_list[1].args[1]['total'], 2)
        self.assertNotIn('111@lid', db.execute.await_args_list[1].args[1]['electorate'])
        self.assertIn('10 minutos', send.await_args.args[1])
        self.assertEqual(db.execute.await_args.args[1]['expiration'], 10)
        self.assertEqual(db.execute.await_args_list[1].args[1]['expiration'], 10)
        self.assertIn(":expiration * INTERVAL '1 minute'", str(db.execute.await_args.args[0]))

    async def test_custom_expiration_sets_persisted_deadline_and_short_notice(self):
        for expiration in (5, 20):
            members = [{'id': '111@c.us', 'role': 'admin'}, {'id': '222@c.us'}]
            db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(scalar='Ana'),
                                  self.result(scalar=7), self.result(scalar=7)]), commit=AsyncMock())
            body = {'data': {'contextInfo': {'mentionedJid': ['222@c.us']}}}
            with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
                  patch.object(ban, 'bot_aliases', AsyncMock(return_value={'111@c.us'})),
                  patch.object(ban, 'PgConnection', self.database(db)),
                  patch.object(ban, 'send_message', AsyncMock()) as send,
                  patch.object(ban, 'request', AsyncMock(return_value={'id': 'true_123@g.us_POLL'}))):
                await ban.handle_ban_command('123@g.us', f'!ban @222 :time 120 :expiration={expiration}', 'CMD', body)
            self.assertEqual(db.execute.await_args_list[1].args[1]['duration'], 120)
            self.assertEqual(db.execute.await_args_list[1].args[1]['expiration'], expiration)
            self.assertEqual(db.execute.await_args.args[1]['expiration'], expiration)
            self.assertIn(f'Expira em {expiration} minutos.', send.await_args.args[1])

    async def test_duplicate_command_does_not_send_another_poll(self):
        members = [{'id': '111@c.us', 'role': 'superadmin'}, {'id': '222@c.us'}]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(scalar='Ana'), self.result()]), commit=AsyncMock())
        body = {'data': {'contextInfo': {'mentionedJid': ['222@c.us']}}}
        with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
              patch.object(ban, 'bot_aliases', AsyncMock(return_value={'111@c.us'})),
              patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'send_message', AsyncMock()),
              patch.object(ban, 'request', AsyncMock()) as request):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', body)
        request.assert_not_awaited()

    async def test_cooldown_blocks_command_before_publishing(self):
        self.availability.return_value = 'Cooldown de 1 hora.'
        members = [{'id': '111@c.us', 'role': 'admin'}, {'id': '222@lid', 'pn': '5522@c.us'}]
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        body = {'data': {'contextInfo': {'mentionedJid': ['222@lid']}}}
        with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
              patch.object(ban, 'bot_aliases', AsyncMock(return_value={'111@c.us'})),
              patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'send_message', AsyncMock()) as send,
              patch.object(ban, 'request', AsyncMock()) as request):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', body)
        request.assert_not_awaited()
        db.execute.assert_not_awaited()
        self.assertEqual(send.await_args.args[1], 'Cooldown de 1 hora.')

    async def test_panel_cancel_during_publish_does_not_reopen_voting(self):
        members = [{'id': '111@c.us', 'role': 'admin'}, {'id': '222@c.us'}]
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(scalar='Ana'),
                              self.result(scalar=7), self.result()]), commit=AsyncMock())
        body = {'data': {'contextInfo': {'mentionedJid': ['222@c.us']}}}
        with (patch.object(ban, 'participants', AsyncMock(return_value=members)),
              patch.object(ban, 'bot_aliases', AsyncMock(return_value={'111@c.us'})),
              patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'request', AsyncMock(return_value={'id': 'true_123@g.us_POLL'})),
              patch.object(ban, 'send_message', AsyncMock()) as send):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', body)
        self.assertIn("status='creating' RETURNING id", str(db.execute.await_args.args[0]))
        self.assertIn('cancelada no painel', send.await_args.args[1])
        self.assertNotIn('mentioned', send.await_args.kwargs)

    def poll_row(self):
        now = datetime.now(timezone.utc)
        return {'id': 7, 'member_count': 2, 'electorate': {'222@lid': '222@lid', '5522@c.us': '222@lid'},
                'opened_at': now - timedelta(minutes=1), 'closes_at': now + timedelta(minutes=9)}

    def vote(self, choices=None, sender='5522@c.us', timestamp=None):
        return {'payload': {'poll': {'id': 'true_123@g.us_POLL'},
                'vote': {'from': sender, 'selectedOptions': ['Sim'] if choices is None else choices,
                         'timestamp': timestamp or int(datetime.now(timezone.utc).timestamp())}}}

    async def test_vote_change_and_retraction_use_same_member_and_ordering(self):
        for choices, expected in [(['Sim'], 'Sim'), (['Não'], 'Não'), ([], '')]:
            db = SimpleNamespace(execute=AsyncMock(return_value=self.result(row=self.poll_row())), commit=AsyncMock())
            with patch.object(ban, 'PgConnection', self.database(db)):
                await ban.record_vote(self.vote(choices))
            sql, args = db.execute.await_args_list[-2].args
            self.assertEqual(args['voter'], '222@lid')
            self.assertEqual(args['choice'], expected)
            self.assertIn('group_ban_vote.timestamp <= EXCLUDED.timestamp', str(sql))

    async def test_outsider_and_vote_outside_window_ignored(self):
        row = self.poll_row()
        for vote in [self.vote(sender='999@c.us'),
                     self.vote(timestamp=int(row['closes_at'].timestamp()) + 1),
                     self.vote(timestamp=int(row['opened_at'].timestamp()) - 60)]:
            db = SimpleNamespace(execute=AsyncMock(return_value=self.result(row=row)), commit=AsyncMock())
            with patch.object(ban, 'PgConnection', self.database(db)):
                await ban.record_vote(vote)
            self.assertEqual(db.execute.await_count, 1)
            db.commit.assert_not_awaited()

    async def test_expired_or_closed_poll_does_not_accept_vote(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=self.result()), commit=AsyncMock())
        with patch.object(ban, 'PgConnection', self.database(db)):
            await ban.record_vote(self.vote())
        db.commit.assert_not_awaited()
        self.assertIn('closes_at > clock_timestamp()', str(db.execute.await_args.args[0]))

    async def test_deadline_finalization_uses_quorum_and_majority_and_is_atomic(self):
        for yes, voted, expected in [(2, 3, 'rejected'), (2, 4, 'rejected'), (3, 4, 'approved')]:
            rows = [{'id': 7, 'member_count': 10}]
            db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(), self.result(rows=rows),
                self.result(tally={'yes': yes, 'voted': voted}), self.result()]), commit=AsyncMock())
            with (patch.object(ban, 'PgConnection', self.database(db)),
                  patch('services.setup.settings', AsyncMock(return_value={'test_mode': False})),
                  patch.object(ban, 'send_results', AsyncMock())):
                await ban.close_due_polls()
            self.assertEqual(db.execute.await_args.args[1]['status'], expected)
            self.assertIn('FOR UPDATE SKIP LOCKED', str(db.execute.await_args_list[1].args[0]))
            self.assertIn('>= member_count', str(db.execute.await_args_list[1].args[0]))
            self.assertIn('clock_timestamp() + duration_minutes', str(db.execute.await_args.args[0]))
            db.commit.assert_awaited_once()

    async def test_all_current_voters_decide_early_and_notify_once(self):
        for choices, expected in [(['Sim', 'Sim', 'Sim'], 'approved'), (['Não', 'Não', 'Não'], 'rejected'),
                                  (['Sim', 'Não', 'Sim'], 'approved'), (['Não', 'Não', 'Sim'], 'rejected')]:
            row = self.poll_row()
            row['member_count'] = 3
            row['electorate']['333@lid'] = '333@lid'
            row['electorate']['444@lid'] = '444@lid'
            votes, status = {}, ['open']
            async def execute(statement, params):
                sql = str(statement)
                if 'SELECT *' in sql:
                    return self.result(row=row if status[0] == 'open' else None)
                if 'INSERT INTO manager.group_ban_vote' in sql:
                    previous = votes.get(params['voter'])
                    if previous is None or previous['timestamp'] <= params['timestamp']:
                        votes[params['voter']] = params
                if 'FILTER (WHERE' in sql:
                    return self.result(tally={'yes': sum(v['choice']=='Sim' for v in votes.values()),
                                             'voted': sum(v['choice'] in ('Sim','Não') for v in votes.values())})
                if 'SET status=:status' in sql:
                    status[0] = params['status']
                return self.result()
            db = SimpleNamespace(execute=AsyncMock(side_effect=execute), commit=AsyncMock())
            with (patch.object(ban, 'PgConnection', self.database(db)),
                  patch.object(ban, 'send_results', AsyncMock()) as notify):
                for choice, sender in zip(choices[:2], ('5522@c.us','333@lid')):
                    await ban.record_vote(self.vote([choice], sender=sender))
                    self.assertEqual(status[0], 'open')
                    notify.assert_not_awaited()
                await ban.record_vote(self.vote([choices[2]], sender='444@lid'))
                self.assertEqual(status[0], expected)
                notify.assert_awaited_once()
                await ban.record_vote(self.vote([], sender='333@lid'))
                self.assertEqual(status[0], expected)
                notify.assert_awaited_once()

    async def test_retraction_does_not_count_as_full_participation(self):
        row = self.poll_row()
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(row=row), self.result(),
            self.result(tally={'yes': 1, 'voted': 1})]), commit=AsyncMock())
        with (patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'send_results', AsyncMock()) as notify):
            await ban.record_vote(self.vote([]))
        self.assertEqual(db.execute.await_count, 3)
        self.assertEqual(db.execute.await_args_list[1].args[1]['choice'], '')
        self.assertIn("choice IN ('Sim','Não')", str(db.execute.await_args.args[0]))
        notify.assert_not_awaited()

    async def test_decisions_are_communicated_and_notice_is_marked(self):
        for status, text in [('approved', 'aprovado por 30 minutos'), ('rejected', 'não aprovado')]:
            row = {'id': 7, 'status': status, 'chat_id': '123@g.us',
                   'target_name': 'Ana', 'duration_minutes': 30, 'member_count': 10}
            db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(rows=[row]),
                                 self.result(tally={'yes': 6, 'voted': 8}), self.result()]),
                                 commit=AsyncMock())
            with (patch.object(ban, 'PgConnection', self.database(db)),
                  patch.object(ban, 'request', AsyncMock()) as send):
                await ban.send_results()
            self.assertIn(text, send.await_args.kwargs['payload']['text'])
            self.assertEqual(send.await_args.kwargs['payload']['chatId'], '123@g.us')
            self.assertIn('notice_sent=TRUE', str(db.execute.await_args.args[0]))

    async def test_timeout_notice_explains_zero_votes_tie_or_no_majority(self):
        for yes, voted, reason in [(0, 0, 'quórum insuficiente'), (2, 4, 'empate'), (1, 4, 'maioria votou Não')]:
            row = {'id': 7, 'status': 'rejected', 'chat_id': '123@g.us', 'target_name': 'Ana',
                   'duration_minutes': 30, 'member_count': 10}
            db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(rows=[row]),
                self.result(tally={'yes': yes, 'voted': voted}), self.result()]), commit=AsyncMock())
            with (patch.object(ban, 'PgConnection', self.database(db)),
                  patch.object(ban, 'request', AsyncMock()) as send):
                await ban.send_results()
            notice = send.await_args.kwargs['payload']['text']
            self.assertIn(reason, notice)
            self.assertIn(f'{voted}/10 votantes', notice)

    async def test_failed_result_delivery_remains_pending_and_is_retried(self):
        import httpx
        row = {'id': 7, 'status': 'approved', 'chat_id': '123@g.us', 'target_name': 'Ana',
               'duration_minutes': 30, 'member_count': 10}
        tally = self.result(tally={'yes': 3, 'voted': 4})
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(rows=[row]), tally,
            self.result(rows=[row]), tally, self.result()]), commit=AsyncMock())
        with (patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'request', AsyncMock(side_effect=[httpx.ConnectError('offline'), {}])) as send,
              patch.object(ban.logger, 'error', AsyncMock())):
            await ban.send_results()
            self.assertEqual(db.execute.await_count, 2)
            await ban.send_results()
        self.assertEqual(send.await_count, 2)
        self.assertEqual(sum('notice_sent=TRUE' in str(call.args[0]) for call in db.execute.await_args_list), 1)

    async def test_scheduler_still_delivers_pending_notices_if_finalization_fails(self):
        with (patch('services.setup.settings', AsyncMock(return_value={'test_mode': False})),
              patch.object(ban, 'finalize_due_polls', AsyncMock(side_effect=RuntimeError('database unavailable'))),
              patch.object(ban.logger, 'error', AsyncMock()) as error,
              patch.object(ban, 'send_results', AsyncMock()) as send):
            await ban.close_due_polls()
        send.assert_awaited_once()
        self.assertEqual(error.await_args.args[1], 'FinalizationFailed')

    async def test_gows_group_participant_device_suffix_and_string_ms_timestamp(self):
        body = self.vote(timestamp=str(int(datetime.now(timezone.utc).timestamp() * 1000)))
        body['payload']['vote'].update({'from': '123@g.us', 'participant': '5522:28@c.us'})
        db = SimpleNamespace(execute=AsyncMock(return_value=self.result(row=self.poll_row())), commit=AsyncMock())
        with patch.object(ban, 'PgConnection', self.database(db)):
            await ban.record_vote(body)
        self.assertEqual(db.execute.await_args_list[1].args[1]['voter'], '222@lid')
        self.assertEqual(db.execute.await_args_list[1].args[1]['choice'], 'Sim')
        db.commit.assert_awaited_once()

    async def test_failed_decryption_invalidates_poll(self):
        db = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())
        with patch.object(ban, 'PgConnection', self.database(db)):
            await ban.record_failed_vote(self.vote())
        self.assertIn("status='invalid'", str(db.execute.await_args.args[0]))
        db.commit.assert_awaited_once()

    async def test_active_ban_deletes_original_message_and_stops_processing(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=self.result(row=(7,))))
        data = {'key': {'id': 'MSG', 'participant': '222@lid', 'participantAlt': '5522@s.whatsapp.net',
                        'providerId': 'false_123@g.us_MSG_222@lid'}, 'messageTimestamp': 1800000000}
        with (patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'request', AsyncMock()) as request):
            self.assertTrue(await ban.enforce_ban(data, '123@g.us'))
        request.assert_awaited_once_with('DELETE', f'/api/{ban.waha_session}/chats/123%40g.us/messages/false_123%40g.us_MSG_222%40lid')
        sql, args = db.execute.await_args.args
        self.assertEqual(args['aliases'], ['222@lid', '5522@c.us'])
        self.assertIn('ban_until > clock_timestamp()', str(sql))
        self.assertEqual(args['chat'], '123@g.us')

    async def test_unbanned_or_expired_member_message_is_not_deleted(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=self.result()))
        data = {'key': {'id': 'MSG', 'participant': '222@lid'}, 'messageTimestamp': 1800000000}
        with (patch.object(ban, 'PgConnection', self.database(db)),
              patch.object(ban, 'request', AsyncMock()) as request):
            self.assertFalse(await ban.enforce_ban(data, '123@g.us'))
        request.assert_not_awaited()


class BanCooldownTests(unittest.IsolatedAsyncioTestCase):
    result = BanFlowTests.result

    async def test_subscriptions_are_checked_before_starting_a_poll(self):
        config = {'status': 'WORKING', 'config': {'webhooks': [{
            'url': 'http://api:9001/webhook/waha', 'events': ['message.any','poll.vote','poll.vote.failed']}]}}
        with (patch.object(ban, 'request', AsyncMock(return_value=config)) as request,
              patch('scripts.waha_session.configure_session', AsyncMock()) as configure,
              patch('scripts.waha_session.get_webhook_url', return_value='http://api:9001/webhook/waha')):
            await ban.ensure_ban_webhooks()
        configure.assert_not_awaited()
        self.assertEqual(request.await_args.args[0], 'GET')

    async def test_disconnected_session_produces_a_clear_reply_instead_of_silence(self):
        with (patch.object(ban, '_handle_ban_command', AsyncMock(side_effect=ban.BanUnavailableError('O WhatsApp está reconectando.'))),
              patch.object(ban.logger, 'error', AsyncMock()),
              patch.object(ban, 'request', AsyncMock()) as request):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', {})
        self.assertEqual(request.await_args.args, ('POST', '/api/sendText'))
        self.assertIn('reconectando', request.await_args.kwargs['payload']['text'])

    async def test_unexpected_command_error_is_logged_and_replied_without_database(self):
        with (patch.object(ban, '_handle_ban_command', AsyncMock(side_effect=RuntimeError('db error'))),
              patch.object(ban.logger, 'error', AsyncMock()) as log,
              patch.object(ban, 'request', AsyncMock()) as request):
            await ban.handle_ban_command('123@g.us', '!ban @222', 'CMD', {})
        self.assertEqual(log.await_args.args[1], 'CommandFailed')
        self.assertIn('Não consegui concluir', request.await_args.kwargs['payload']['text'])

    def test_open_poll_and_active_ban_block_new_vote(self):
        now = datetime.now(timezone.utc)
        for status in ('creating', 'open', 'approved'):
            row = {'status': status, 'ban_until': now + timedelta(minutes=30)}
            self.assertIsNotNone(ban.cooldown_message(row, now))

    def test_one_hour_after_rejection_cancellation_or_invalid_vote(self):
        now = datetime.now(timezone.utc)
        for status in ('rejected', 'cancelled', 'invalid'):
            for elapsed, blocked in [(0, True), (59, True), (60, False), (61, False)]:
                row = {'status': status, 'finished_at': now - timedelta(minutes=elapsed)}
                self.assertEqual(ban.cooldown_message(row, now) is not None, blocked)

    def test_ban_cooldown_starts_at_actual_end_not_approval(self):
        now = datetime.now(timezone.utc)
        for status in ('approved', 'revoked'):
            for elapsed, blocked in [(0, True), (59, True), (60, False)]:
                row = {'status': status, 'ban_until': now - timedelta(minutes=elapsed),
                       'finished_at': now - timedelta(hours=4)}
                self.assertEqual(ban.cooldown_message(row, now) is not None, blocked)

    async def test_availability_locks_aliases_and_scopes_history_to_group(self):
        db = SimpleNamespace(execute=AsyncMock(side_effect=[self.result(), self.result(), self.result()]),
                             commit=AsyncMock())
        result = await ban.check_ban_availability(db, '123@g.us', ['5522@c.us', '222@lid'])
        self.assertIsNone(result)
        calls = db.execute.await_args_list
        self.assertIn('pg_advisory_xact_lock', str(calls[0].args[0]))
        self.assertTrue(calls[0].args[1]['key'].endswith(':222@lid'))
        self.assertTrue(calls[1].args[1]['key'].endswith(':5522@c.us'))
        self.assertEqual(calls[2].args[1]['chat'], '123@g.us')
        self.assertEqual(calls[2].args[1]['session'], ban.waha_session)
        self.assertIn("ban_until + INTERVAL '1 hour'", str(calls[2].args[0]))
        self.assertIn("finished_at + INTERVAL '1 hour'", str(calls[2].args[0]))
        # Keep locks until the caller reserves its poll and commits.
        db.commit.assert_not_awaited()


class BanWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cached = patch('api.routes.webhook.waha.services.cached_ban_decision', AsyncMock(return_value=None))
        cached.start()
        self.addCleanup(cached.stop)
        audit = patch('api.routes.webhook.waha.services.persist_ban_deletion', AsyncMock())
        self.audit = audit.start()
        self.addCleanup(audit.stop)

    post = waha_tests.WahaWebhookTests.post
    asyncTearDown = waha_tests.WahaWebhookTests.asyncTearDown

    async def test_plain_and_bot_prefixed_ban_use_handler_instead_of_agent(self):
        from api.routes.webhook.waha.processors import common
        for command in ('!ban', '@Gork !ban @andre :time=5', '@5511 !BAN @5522 :time 30min'):
            with (patch.object(common, 'get_disabled_command_message', AsyncMock(return_value=None)),
                  patch.object(common, 'handle_conversation_agent', AsyncMock()) as agent,
                  patch.object(ban, 'handle_ban_command', AsyncMock()) as handler):
                await common.process_commands(command, '123@g.us', 'CMD', SimpleNamespace(id=1),
                                              {}, 2, Mock(), Mock(), {}, Mock())
            handler.assert_awaited_once_with('123@g.us', command, 'CMD', {})
            agent.assert_not_awaited()

    async def test_poll_webhook_authenticated_and_dispatched(self):
        body = waha_tests.event()
        body['event'] = 'poll.vote'
        body['payload'] = {'poll': {'id': 'POLL'}, 'vote': {'from': '123@c.us'}}
        with patch('api.routes.webhook.waha.router.process_waha_webhook', AsyncMock()) as process:
            response = await self.post(body)
            from api.routes.webhook.waha.router import background_tasks
            await asyncio.gather(*list(background_tasks))
        self.assertEqual(response.status_code, 200)
        process.assert_awaited_once()

    async def test_malformed_poll_rejected(self):
        body = waha_tests.event()
        body['event'] = 'poll.vote'
        self.assertEqual((await self.post(body)).status_code, 400)

    async def test_poll_persistence_failure_returns_retryable_status(self):
        body = waha_tests.event()
        body['event'] = 'poll.vote'
        body['payload'] = {'poll': {'id': 'POLL'}, 'vote': {'participant': '222@lid'}}
        with (patch('api.routes.webhook.waha.router.process_waha_webhook', AsyncMock(side_effect=RuntimeError('db failed'))),
              patch('api.routes.webhook.waha.router.logger.error', AsyncMock())):
            response = await self.post(body)
        self.assertEqual(response.status_code, 503)

    async def test_banned_message_is_deleted_before_normal_pipeline(self):
        from api.routes.webhook.waha import services
        body = waha_tests.event()
        with (patch.object(services, 'moderate_group_message', AsyncMock(return_value=True)) as moderate,
              patch.object(services, 'request', AsyncMock()) as request,
              patch.object(services, 'save_reference', AsyncMock()) as save,
              patch.object(services, 'process_webhook', AsyncMock()) as process):
            await services.process_waha_webhook(body, Mock())
        moderate.assert_awaited_once()
        self.assertEqual(moderate.await_args.args[0]['data']['key']['providerId'], body['payload']['id'])
        request.assert_not_awaited()
        save.assert_not_awaited()
        process.assert_not_awaited()

    async def test_ban_deletes_text_audio_files_and_other_messages_before_processing(self):
        from api.routes.webhook.waha import services
        kinds = ('conversation', 'imageMessage', 'videoMessage', 'audioMessage',
                 'documentMessage', 'stickerMessage', 'contactMessage', 'locationMessage',
                 'pollCreationMessage', 'viewOnceMessage')
        for kind in kinds:
            with self.subTest(kind=kind):
                native = {kind: 'texto' if kind == 'conversation' else {}}
                if kind == 'viewOnceMessage':
                    native = {kind: {'message': {'imageMessage': {'mimetype': 'image/jpeg'}}}}
                body = waha_tests.event(body='', _data={'Message': native})
                result = Mock()
                result.first.return_value = (7,)
                db = SimpleNamespace(execute=AsyncMock(return_value=result))
                @asynccontextmanager
                async def connection():
                    yield db
                with (patch.object(services, 'settings', AsyncMock(return_value={'test_mode': False})),
                      patch.object(ban, 'PgConnection', connection),
                      patch.object(ban, 'request', AsyncMock()) as request,
                      patch.object(services, 'save_reference', AsyncMock()) as save,
                      patch.object(services, 'process_webhook', AsyncMock()) as process):
                    await services.process_waha_webhook(body, Mock())
                self.assertEqual(request.await_args.args[0], 'DELETE')
                self.assertIn('/messages/', request.await_args.args[1])
                save.assert_not_awaited()
                process.assert_not_awaited()

    async def test_test_mode_prevents_poll_votes_and_moderation(self):
        from api.routes.webhook.waha import services
        from api.routes.webhook.waha.normalize import normalize_webhook
        with (patch.object(services, 'settings', AsyncMock(return_value={'test_mode': True})),
              patch.object(ban, 'record_vote', AsyncMock()) as vote,
              patch.object(ban, 'enforce_ban', AsyncMock()) as enforce):
            await services.process_waha_webhook({'event': 'poll.vote', 'payload': {}}, Mock())
            self.assertFalse(await services.moderate_group_message(normalize_webhook(waha_tests.event())))
        vote.assert_not_awaited()
        enforce.assert_not_awaited()

    async def test_mentions_all_reaches_waha_without_user_jid_conversion(self):
        from external.waha.message import send_message
        with (patch('external.waha.message.request', AsyncMock(return_value={'id': 'true_123@g.us_SENT'})) as send,
              patch('external.waha.identifiers.save_reference', AsyncMock())):
            await send_message('123@g.us', '@all votação', simulate_typing=False, mentioned=['all'])
        self.assertEqual(send.await_args.kwargs['payload']['mentions'], ['all'])

    async def test_explicit_group_mentions_send_each_jid_and_matching_tags(self):
        from external.waha.message import send_message
        notice = 'Votação para banimento de Ana.\nExpira em 10 minutos.\n\n@222 @333'
        with (patch('external.waha.message.request', AsyncMock(return_value={'id': 'true_123@g.us_SENT'})) as send,
              patch('external.waha.identifiers.save_reference', AsyncMock())):
            await send_message('123@g.us', notice, simulate_typing=False,
                               mentioned=['222@lid', '333@s.whatsapp.net'])
        self.assertEqual(send.await_args.kwargs['payload']['mentions'], ['222@lid', '333@c.us'])
        self.assertEqual(send.await_args.kwargs['payload']['text'], notice)


if __name__ == '__main__':
    unittest.main()
