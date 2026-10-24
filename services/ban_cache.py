from security.crypto import encrypt, decrypt
from security.sql import ban_text as text
"""Shared moderation snapshot. Cache failures fall back to PostgreSQL."""
import asyncio
import json
import time

import redis.asyncio as redis
from redis.exceptions import RedisError

from database import PgConnection
from external.waha.base import chat_id, waha_session
from utils import get_env_var


_redis = None
KEY = f'gork:ban-snapshot:{waha_session}'
VERSION = KEY + ':version'
INVALIDATE = "redis.call('INCR', KEYS[2]); return redis.call('DEL', KEYS[1])"
PUBLISH = """if (redis.call('GET', KEYS[2]) or '0') ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[1], ARGV[2], 'EX', 5); return 1"""


def client():
    global _redis
    if _redis is None:
        _redis = redis.from_url(get_env_var('REDIS_URL') or 'redis://localhost:6379/0',
            decode_responses=True, socket_connect_timeout=0.15, socket_timeout=0.15)
    return _redis


async def invalidate():
    try:
        async with asyncio.timeout(0.2):
            await client().eval(INVALIDATE, 2, KEY, VERSION)
    except (RedisError, OSError, TimeoutError):
        pass


async def snapshot():
    try:
        async with asyncio.timeout(0.2):
            cached = await client().get(KEY)
            if cached:
                return json.loads(decrypt(cached, "ban.cache"))
            version = await client().get(VERSION) or '0'
        async with PgConnection() as db:
            mode = (await db.execute(text('SELECT test_mode FROM base.app_settings WHERE id=1'))).scalar_one()
            rows = [] if mode else (await db.execute(text('''SELECT chat_id, target_aliases,
                EXTRACT(EPOCH FROM ban_started_at) AS started, EXTRACT(EPOCH FROM ban_until) AS expires_at
                FROM manager.group_ban_poll WHERE session=:session AND status='approved'
                AND ban_until > clock_timestamp()'''), {'session': waha_session})).mappings().all()
            result = {'test_mode': mode, 'bans': [dict(chat=row['chat_id'], aliases=row['target_aliases'],
                started=int(row['started']), until=float(row['expires_at'])) for row in rows]}
        async with asyncio.timeout(0.2):
            # A revoke during the SQL read must prevent publishing a stale snapshot.
            if not await client().eval(PUBLISH, 2, KEY, VERSION, version, encrypt(json.dumps(result), "ban.cache")):
                return None
        return result
    except (RedisError, OSError, TimeoutError, ValueError, TypeError):
        return None


async def decision(data: dict, remote: str) -> bool | None:
    state = await snapshot()
    if state is None:
        return None
    if state['test_mode']:
        return False
    sender = {chat_id(data['key'][k]) for k in ('participant', 'participantAlt') if data['key'].get(k)}
    now = time.time()
    return any(ban['chat'] == remote and ban['until'] > now
               and data['messageTimestamp'] >= ban['started'] and sender.intersection(ban['aliases'])
               for ban in state['bans'])
