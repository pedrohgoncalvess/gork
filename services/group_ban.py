"""Durable moderation: decide when everyone votes or at the configured deadline."""
import json
import asyncio
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import text

from database import PgConnection
from external.waha.base import chat_id, request, segment, waha_session
from external.waha.identifiers import stanza_id
from external.waha.message import send_message
from log import logger
from services.ban_cache import invalidate as invalidate_ban_cache


ADMIN_REQUIRED = 'Preciso ser administrador do grupo para abrir a votação e excluir mensagens.'
USAGE = 'Use !ban @usuário :time 30min :expiration 10. :time aceita 3hr, 30min, 120 ou 1:30; padrão 30 minutos, máximo 3 horas. :expiration é o prazo da votação em minutos: de 5 a 20, padrão 10.'


def duration_minutes(command: str) -> int:
    parameters = re.findall(r'(?<!\S):time\b', command, re.I)
    if not parameters:
        return 30
    matches = list(re.finditer(r'(?<!\S):time(?:=|\s+)(\S+)', command, re.I))
    if len(parameters) != 1 or len(matches) != 1:
        raise ValueError(USAGE)
    value = matches[0][1].lower()
    if re.fullmatch(r'\d+:\d{2}', value):
        hours, minutes = map(int, value.split(':'))
        if minutes >= 60:
            raise ValueError(USAGE)
        total = hours * 60 + minutes
    elif re.fullmatch(r'\d+(?:hr|min)?', value):
        total = int(re.match(r'\d+', value)[0]) * (60 if value.endswith('hr') else 1)
    else:
        raise ValueError(USAGE)
    if not 1 <= total <= 180:
        raise ValueError('O tempo deve ser de 1 a 180 minutos. ' + USAGE)
    return total


def expiration_minutes(command: str) -> int:
    parameters = re.findall(r'(?<!\S):expiration\b', command, re.I)
    if not parameters:
        return 10
    matches = list(re.finditer(r'(?<!\S):expiration(?:=|\s+)(\S+)', command, re.I))
    error = 'Use :expiration de 5 a 20 minutos (padrão: 10).'
    if len(parameters) != 1 or len(matches) != 1 or not re.fullmatch(r'[0-9]+', matches[0][1]):
        raise ValueError(error)
    expiration = int(matches[0][1])
    if not 5 <= expiration <= 20:
        raise ValueError(error)
    return expiration


def aliases(member: dict) -> list[str]:
    return sorted({chat_id(member[key]) for key in ('id', 'pn', 'lid') if member.get(key)})


def is_admin(member: dict) -> bool:
    return member.get('role') in ('admin', 'superadmin')


def electorate(members: list[dict]) -> dict[str, str]:
    return {alias: chat_id(member['id']) for member in members for alias in aliases(member)}


def quorum(total: int) -> int:
    return max(3, (total + 2) // 3)


def approved(yes: int, total: int, voted: int) -> bool:
    return total > 0 and voted >= quorum(total) and yes * 2 > voted


def voter_jid(value) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    value = re.sub(r':\d+(?=@)', '', chat_id(value))
    return value if re.fullmatch(r'\d+@(?:c\.us|lid)', value) else None


class BanUnavailableError(RuntimeError):
    pass


async def ensure_ban_webhooks():
    # Configuration updates can restart WAHA. Never reconfigure during a command.
    session = await request('GET', f'/api/sessions/{segment(waha_session)}', timeout=10)
    if session.get('status') != 'WORKING':
        raise BanUnavailableError('O WhatsApp está reconectando. Tente abrir a votação novamente em instantes.')
    from scripts.waha_session import get_webhook_url
    webhooks = (session.get('config') or {}).get('webhooks') or []
    expected = {'message.any', 'poll.vote', 'poll.vote.failed'}
    subscribed = any(hook.get('url') == get_webhook_url() and
        ('*' in (hook.get('events') or []) or expected.issubset(hook.get('events') or [])) for hook in webhooks)
    if not subscribed:
        raise BanUnavailableError('Os eventos de votação não estão configurados. Reconfigure a conexão no painel antes de abrir a votação.')


async def participants(group: str) -> list[dict]:
    result = await request('GET', f'/api/{segment(waha_session)}/groups/{segment(group)}/participants/v2')
    return result if isinstance(result, list) else result['participants']


async def bot_aliases() -> set[str]:
    result = await request('GET', f'/api/sessions/{segment(waha_session)}')
    return set(aliases(result.get('me') or {}))


def cooldown_message(row: dict, now: datetime) -> str | None:
    if row['status'] in ('creating', 'open'):
        return 'Já existe uma votação em andamento para esse usuário. Aguarde o encerramento e mais 1 hora.'
    if row['status'] in ('approved', 'revoked'):
        end = row['ban_until']
        if row['status'] == 'approved' and end and end > now:
            return 'Esse usuário ainda está banido. Outra votação só poderá ser aberta 1 hora após o fim do ban.'
    else:
        end = row['finished_at']
    if end and end + timedelta(hours=1) > now:
        available = (end + timedelta(hours=1)).astimezone(ZoneInfo('America/Sao_Paulo'))
        return f'Cooldown de 1 hora. Nova votação liberada em {available:%d/%m às %H:%M} (Brasília).'
    return None


async def check_ban_availability(db, remote: str, target_ids: list[str]) -> str | None:
    # Lock every known alias in a stable order. Workers targeting the same member
    # by phone or LID must check cooldown and reserve the next poll serially.
    for alias in sorted(target_ids):
        await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
                         {'key': f'group-ban:{waha_session}:{remote}:{alias}'})
    rows = (await db.execute(text('''SELECT status, ban_until, finished_at FROM manager.group_ban_poll
        WHERE session=:session AND chat_id=:chat AND target_aliases ?| CAST(:aliases AS text[])
        AND (status IN ('creating','open')
            OR (status IN ('approved','revoked') AND ban_until + INTERVAL '1 hour' > clock_timestamp())
            OR (status IN ('rejected','cancelled','invalid') AND finished_at + INTERVAL '1 hour' > clock_timestamp()))
        ORDER BY opened_at DESC'''),
        {'session': waha_session, 'chat': remote, 'aliases': target_ids})).mappings().all()
    now = datetime.now(timezone.utc)
    for row in rows:
        reason = cooldown_message(row, now)
        if reason:
            return reason
    return None


async def handle_ban_command(remote: str, command: str, message_id: str, body: dict):
    try:
        async with asyncio.timeout(25):
            await _handle_ban_command(remote, command, message_id, body)
    except Exception as error:
        await logger.error('GroupBan', 'CommandFailed', f'{type(error).__name__}: {error}')
        message = (str(error) if isinstance(error, BanUnavailableError) else
                   'Não consegui concluir o !ban agora. Confira o painel e tente novamente em instantes.')
        # Do not depend on the failed DB transaction or quote lookup to report it.
        await request('POST', '/api/sendText', payload={
            'session': waha_session, 'chatId': remote, 'text': message}, timeout=10)


async def _handle_ban_command(remote: str, command: str, message_id: str, body: dict):
    async def reply(value):
        await send_message(remote, value, message_id, simulate_typing=False)

    if not remote.endswith('@g.us'):
        await reply('O comando !ban só funciona em grupos.')
        return
    members = await participants(remote)
    own_ids = await bot_aliases()
    own = next((m for m in members if own_ids.intersection(aliases(m))), None)
    if not own or not is_admin(own):
        await reply(ADMIN_REQUIRED)
        return
    try:
        duration = duration_minutes(command)
        expiration = expiration_minutes(command)
    except ValueError as error:
        await reply(str(error))
        return
    mentioned = {chat_id(jid) for jid in body['data'].get('contextInfo', {}).get('mentionedJid', [])}
    # A leading @Gork is a routing mention, not a second moderation target.
    targets = [m for m in members if mentioned.intersection(aliases(m))
               and not own_ids.intersection(aliases(m))]
    if len(targets) != 1:
        await reply('Mencione exatamente um membro do grupo. ' + USAGE)
        return
    target = targets[0]
    target_ids = aliases(target)
    if own_ids.intersection(target_ids):
        await reply('Não posso aplicar esse banimento a mim mesmo.')
        return
    voters = electorate([member for member in members if not own_ids.intersection(aliases(member))])
    async with PgConnection() as db:
        blocked = await check_ban_availability(db, remote, target_ids)
        if blocked:
            await db.commit()
            await reply(blocked)
            return
        # Check only after the DB has ruled out an existing vote/ban/cooldown.
        await ensure_ban_webhooks()
        # A phone number and a LID represent the same member; use the v2 member ID.
        name = (await db.execute(text('''SELECT name FROM base."user"
            WHERE src_id = ANY(:ids) OR phone_number = ANY(:ids)
            ORDER BY updated_at DESC NULLS LAST LIMIT 1'''),
            {'ids': [jid.split('@')[0] for jid in target_ids]})).scalar_one_or_none()
        name = name or target.get('name')
        if not name:
            try:
                contact = await request('GET',
                    f'/api/{segment(waha_session)}/contacts/{segment(target["id"])}')
                name = contact.get('name') or contact.get('pushname') or contact.get('pushName')
            except httpx.HTTPError:
                pass
        name = name or target['id'].split('@')[0]
        row = (await db.execute(text('''INSERT INTO manager.group_ban_poll
            (session, chat_id, command_id, target_id, target_aliases, target_name,
             electorate, member_count, duration_minutes, closes_at)
            VALUES (:session, :chat, :command, :target, CAST(:aliases AS jsonb), :name,
                    CAST(:electorate AS jsonb), :total, :duration,
                    clock_timestamp() + :expiration * INTERVAL '1 minute')
            ON CONFLICT DO NOTHING RETURNING id'''), {
                'session': waha_session, 'chat': remote, 'command': message_id,
                'target': chat_id(target['id']), 'aliases': json.dumps(target_ids),
                'name': name, 'electorate': json.dumps(voters),
                'total': len(set(voters.values())), 'duration': duration,
                'expiration': expiration,
            })).scalar_one_or_none()
        await db.commit()
    if row is None:
        await reply('Esse comando já foi processado ou já existe uma votação aberta para esse usuário.')
        return
    try:
        poll = await request('POST', '/api/sendPoll', payload={
            'session': waha_session, 'chatId': remote,
            'poll': {'name': f'Banimento {name}', 'options': ['Sim', 'Não'], 'multipleAnswers': False},
        })
        async with PgConnection() as db:
            published = (await db.execute(text('''UPDATE manager.group_ban_poll SET poll_id=:poll, status='open',
                opened_at=clock_timestamp(), closes_at=clock_timestamp() + :expiration * INTERVAL '1 minute'
                WHERE id=:id AND status='creating' RETURNING id'''),
                {'poll': stanza_id(poll['id']), 'id': row, 'expiration': expiration})).scalar_one_or_none()
            await db.commit()
        if published is None:
            await reply('A votação foi cancelada no painel e não será apurada.')
            return
    except Exception:
        async with PgConnection() as db:
            await db.execute(text("UPDATE manager.group_ban_poll SET status='failed' WHERE id=:id AND status='creating'"), {'id': row})
            await db.commit()
        raise
    # Explicit member IDs plus matching visible tags avoid relying on @all expansion.
    mentions = sorted(set(voters.values()))
    tags = ' '.join('@' + identifier.split('@')[0] for identifier in mentions)
    await send_message(remote,
        f'Votação para banimento de {name}.\nExpira em {expiration} minutos.\n\n{tags}',
        simulate_typing=False, mentioned=mentions)


async def record_vote(body: dict):
    payload = body.get('payload') or {}
    poll, vote = payload.get('poll') or {}, payload.get('vote') or {}
    if not isinstance(poll.get('id'), str):
        return
    timestamp = vote.get('timestamp')
    if isinstance(timestamp, str) and timestamp.isdigit():
        timestamp = int(timestamp)
    if not isinstance(timestamp, int) or isinstance(timestamp, bool):
        return
    # Be prepared for the provider switching from seconds to milliseconds.
    seconds = timestamp / 1000 if timestamp > 100_000_000_000 else timestamp
    options = vote.get('selectedOptions')
    if not isinstance(options, list) or len(options) > 1 or any(x not in ('Sim', 'Não') for x in options):
        return
    async with PgConnection() as db:
        row = (await db.execute(text('''SELECT * FROM manager.group_ban_poll
            WHERE session=:session AND poll_id=:poll AND status='open'
            AND closes_at > clock_timestamp() FOR UPDATE'''),
            {'session': waha_session, 'poll': stanza_id(poll['id'])})).mappings().first()
        if not row:
            return
        if not row['opened_at'].timestamp() - 1 <= seconds < row['closes_at'].timestamp():
            return
        info = (payload.get('_data') or {}).get('Info') or {}
        candidates = (vote.get('participant'), vote.get('from'), vote.get('participantAlt'),
                      info.get('Sender'), info.get('SenderAlt'))
        voter = next((row['electorate'][jid] for value in candidates
                      if (jid := voter_jid(value)) in row['electorate']), None)
        if not voter or vote.get('fromMe'):
            await logger.info('GroupBan', 'VoteIgnored', f'poll={row["id"]} reason=unknown-voter-or-own-vote')
            return
        await db.execute(text('''INSERT INTO manager.group_ban_vote (poll_id, voter_id, choice, timestamp)
            VALUES (:poll, :voter, :choice, :timestamp)
            ON CONFLICT (poll_id, voter_id) DO UPDATE
            SET choice=EXCLUDED.choice, timestamp=EXCLUDED.timestamp
            WHERE group_ban_vote.timestamp <= EXCLUDED.timestamp'''),
            {'poll': row['id'], 'voter': voter, 'choice': options[0] if options else '',
             'timestamp': int(seconds * 1000)})
        # The poll lock covers both the updated choice and the decision. Retractions
        # are empty choices and do not count as participation.
        decided = await decide_poll(db, row, require_everyone=True)
        await db.commit()
    if decided:
        await invalidate_ban_cache()
    await logger.info('GroupBan', 'VoteRecorded', f'poll={row["id"]} decided={decided}')
    if decided:
        await send_results()


async def decide_poll(db, row, *, require_everyone=False) -> bool:
    tally = (await db.execute(text('''SELECT
        count(*) FILTER (WHERE choice='Sim') AS yes,
        count(*) FILTER (WHERE choice IN ('Sim','Não')) AS voted
        FROM manager.group_ban_vote WHERE poll_id=:id'''), {'id': row['id']})).mappings().one()
    if require_everyone and tally['voted'] < row['member_count']:
        return False
    passed = approved(tally['yes'], row['member_count'], tally['voted'])
    await db.execute(text('''UPDATE manager.group_ban_poll SET status=:status, finished_at=clock_timestamp(),
        ban_started_at=CASE WHEN :passed THEN clock_timestamp() ELSE NULL END,
        ban_until=CASE WHEN :passed THEN clock_timestamp() + duration_minutes * INTERVAL '1 minute' ELSE NULL END
        WHERE id=:id AND status='open' '''),
        {'id': row['id'], 'status': 'approved' if passed else 'rejected', 'passed': passed})
    return True


async def record_failed_vote(body: dict):
    identifier = (body.get('payload', {}).get('poll') or {}).get('id')
    if not isinstance(identifier, str):
        return
    async with PgConnection() as db:
        # An unreadable change could undo a prior yes: never approve a partial tally.
        await db.execute(text('''UPDATE manager.group_ban_poll SET status='invalid', finished_at=clock_timestamp()
            WHERE session=:session AND poll_id=:poll AND status='open'
            AND closes_at > clock_timestamp()'''),
            {'session': waha_session, 'poll': stanza_id(identifier)})
        await db.commit()


async def close_due_polls():
    from services.setup import settings
    if (await settings())['test_mode']:
        return
    try:
        await finalize_due_polls()
    except Exception as error:
        await logger.error('GroupBan', 'FinalizationFailed', str(error))
    # Retry outstanding notices even when another poll fails to finalize.
    try:
        await send_results()
    except Exception as error:
        await logger.error('GroupBan', 'ResultDeliveryFailed', str(error))


async def finalize_due_polls():
    """Database row locks prevent different workers from deciding a poll twice."""
    async with PgConnection() as db:
        # Expire a reservation if a worker died before publishing its poll.
        await db.execute(text("""UPDATE manager.group_ban_poll SET status='failed'
            WHERE session=:session AND status='creating' AND closes_at <= clock_timestamp()"""),
            {'session': waha_session})
        rows = (await db.execute(text('''SELECT * FROM manager.group_ban_poll p
            WHERE session=:session AND status='open' AND (closes_at <= clock_timestamp()
                OR (SELECT count(*) FROM manager.group_ban_vote v
                    WHERE v.poll_id=p.id AND v.choice IN ('Sim','Não')) >= member_count)
            FOR UPDATE SKIP LOCKED'''), {'session': waha_session})).mappings().all()
        for row in rows:
            await decide_poll(db, row)
        await db.commit()
    if rows:
        await invalidate_ban_cache()


async def send_results():
    # A durable outbox retries failed announcements on the following tick.
    async with PgConnection() as db:
        rows = (await db.execute(text('''SELECT * FROM manager.group_ban_poll
            WHERE session=:session AND status IN ('approved', 'rejected', 'invalid') AND NOT notice_sent
            FOR UPDATE SKIP LOCKED'''), {'session': waha_session})).mappings().all()
        for row in rows:
            try:
                tally = (await db.execute(text('''SELECT
                    count(*) FILTER (WHERE choice='Sim') AS yes,
                    count(*) FILTER (WHERE choice IN ('Sim','Não')) AS voted
                    FROM manager.group_ban_vote WHERE poll_id=:id'''), {'id': row['id']})).mappings().one()
                no = tally['voted'] - tally['yes']
                summary = f'{tally["yes"]} Sim · {no} Não · {tally["voted"]}/{row["member_count"]} votantes.'
                if row['status'] == 'approved':
                    result = f'Banimento de {row["target_name"]} aprovado por {row["duration_minutes"]} minutos. {summary}'
                elif row['status'] == 'rejected':
                    reason = ('quórum insuficiente' if tally['voted'] < quorum(row['member_count'])
                              else 'empate' if tally['yes'] == no else 'maioria votou Não')
                    result = f'Banimento de {row["target_name"]} não aprovado: {reason}. {summary}'
                else:
                    result = f'Votação de banimento de {row["target_name"]} cancelada: não consegui ler todos os votos. Nenhum banimento foi aplicado. Nova tentativa após o cooldown de 1 hora.'
                # send_message saves a reference and commits a shared session;
                # send directly here so the outbox row remains locked until marked.
                await request('POST', '/api/sendText', payload={
                    'session': waha_session, 'chatId': row['chat_id'], 'text': result,
                })
                await db.execute(text('UPDATE manager.group_ban_poll SET notice_sent=TRUE WHERE id=:id'), {'id': row['id']})
            except Exception as error:
                await logger.error('GroupBan', 'ResultNotice', str(error))
        await db.commit()


async def enforce_ban(data: dict, remote: str, *, known_active=False) -> bool:
    key = data['key']
    if key.get('fromMe') or not remote.endswith('@g.us'):
        return False
    sender = [chat_id(key[k]) for k in ('participant', 'participantAlt') if key.get(k)]
    if not sender:
        return False
    if not known_active:
        async with PgConnection() as db:
            row = (await db.execute(text('''SELECT id FROM manager.group_ban_poll
            WHERE session=:session AND chat_id=:chat AND status='approved'
            AND ban_until > clock_timestamp() AND target_aliases ?| CAST(:aliases AS text[])
            AND to_timestamp(:timestamp) >= date_trunc('second', ban_started_at)
            LIMIT 1'''), {'session': waha_session, 'chat': remote, 'aliases': sender,
                          'timestamp': data['messageTimestamp']})).first()
        if not row:
            return False
    # Include the original sender in the complete group message reference.
    identifier = key.get('providerId') or f'false_{remote}_{key["id"]}_{chat_id(key["participant"])}'
    if identifier.startswith('false_') and not re.search(r'_[^_]+@(?:c\.us|s\.whatsapp\.net|lid)$', identifier):
        identifier += '_' + chat_id(key['participant'])
    try:
        await request('DELETE', f'/api/{segment(waha_session)}/chats/{segment(remote)}/messages/{segment(identifier)}')
    except httpx.HTTPStatusError as error:
        await logger.error('GroupBan', 'DeleteMessage', str(error))
        # Report the failure, never silently claim that moderation worked.
        raise
    return True
