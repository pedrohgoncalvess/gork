"""Substring matching of encrypted identity fields within the application."""
from sqlalchemy import select


async def matching_user_ids(db, query):
    from database.models.base import User
    rows = (await db.execute(select(User.id, User.name))).all()
    needle = query.strip().casefold()
    return [row.id for row in rows if needle in (row.name or '').casefold()]
