"""Authenticated management of temporary group bans and their polls."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.admin.dependencies import get_db
from external.waha.base import waha_session
from services.ban_cache import invalidate as invalidate_ban_cache


router = APIRouter()
BASE = '''WITH bans AS (
    SELECT p.*, g.name AS group_name,
        CASE WHEN p.status='approved' THEN
            CASE WHEN p.ban_until > clock_timestamp() THEN 'active' ELSE 'expired' END
        WHEN p.status='open' THEN
            CASE WHEN p.closes_at <= clock_timestamp() THEN 'closing' ELSE 'voting' END
        WHEN p.status='creating' THEN 'preparing' ELSE p.status END AS display_status
    FROM manager.group_ban_poll p
    LEFT JOIN base."group" g ON g.src_id = replace(p.chat_id, '@g.us', '')
    WHERE p.session=:session
), filtered AS (
    SELECT * FROM bans WHERE
        (:q='' OR target_name ILIKE :search OR chat_id ILIKE :search
               OR target_id ILIKE :search OR group_name ILIKE :search)
        AND (:view='all' OR (:view='active' AND display_status='active')
            OR (:view='voting' AND display_status IN ('voting','preparing','closing'))
            OR (:view='history' AND display_status NOT IN ('active','voting','preparing','closing')))
) '''


@router.get('/bans')
async def list_bans(view: Literal['all', 'active', 'voting', 'history'] = 'all',
                    q: str = Query('', max_length=100), offset: int = Query(0, ge=0),
                    limit: int = Query(30, ge=1, le=100), db=Depends(get_db)):
    params = {'session': waha_session, 'view': view, 'q': q.strip(),
              'search': '%' + q.strip() + '%', 'offset': offset, 'limit': limit}
    total = (await db.execute(text(BASE + 'SELECT count(*) FROM filtered'), params)).scalar_one()
    rows = (await db.execute(text(BASE + '''SELECT f.id, f.chat_id, f.target_id, f.target_name,
        f.group_name, f.display_status AS status, f.member_count, f.duration_minutes,
        f.opened_at, f.closes_at, f.ban_started_at, f.ban_until,
        CASE WHEN f.status IN ('approved','revoked') THEN f.ban_until + INTERVAL '1 hour'
             WHEN f.status IN ('rejected','cancelled','invalid') THEN f.finished_at + INTERVAL '1 hour'
             ELSE NULL END AS next_vote_at,
        (SELECT count(*) FROM manager.group_ban_vote v WHERE v.poll_id=f.id AND v.choice='Sim') AS yes_votes,
        (SELECT count(*) FROM manager.group_ban_vote v WHERE v.poll_id=f.id AND v.choice='Não') AS no_votes
        FROM filtered f ORDER BY
            CASE WHEN display_status='active' THEN 0
                 WHEN display_status IN ('voting','preparing','closing') THEN 1 ELSE 2 END,
            opened_at DESC, id DESC LIMIT :limit OFFSET :offset'''), params)).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        for key in ('opened_at', 'closes_at', 'ban_started_at', 'ban_until', 'next_vote_at'):
            item[key] = item[key].isoformat() if item.get(key) else None
        items.append(item)
    return JSONResponse({'items': items, 'total': total, 'offset': offset, 'limit': limit},
                        headers={'Cache-Control': 'no-store'})


@router.post('/bans/{identifier}/cancel')
async def cancel_poll(identifier: int, db=Depends(get_db)):
    return await stop_ban(db, identifier, False)


@router.post('/bans/{identifier}/revoke')
async def revoke_ban(identifier: int, db=Depends(get_db)):
    return await stop_ban(db, identifier, True)


async def stop_ban(db, identifier: int, revoke: bool):
    condition = "status='approved' AND ban_until > clock_timestamp()" if revoke else "status IN ('creating','open')"
    row = (await db.execute(text(f'''UPDATE manager.group_ban_poll
        SET status=:status, notice_sent=TRUE, finished_at=COALESCE(finished_at, clock_timestamp()),
            ban_until=CASE WHEN :revoke THEN clock_timestamp() ELSE ban_until END
        WHERE id=:id AND session=:session AND {condition} RETURNING id'''),
        {'id': identifier, 'session': waha_session, 'status': 'revoked' if revoke else 'cancelled',
         'revoke': revoke})).scalar_one_or_none()
    if row is None:
        exists = (await db.execute(text('SELECT id FROM manager.group_ban_poll WHERE id=:id AND session=:session'),
                                  {'id': identifier, 'session': waha_session})).scalar_one_or_none()
        raise HTTPException(404 if exists is None else 409,
                            'Registro não encontrado.' if exists is None else 'O estado mudou. Atualize a lista e tente novamente.')
    await db.commit()
    await invalidate_ban_cache()
    return {'ok': True}
