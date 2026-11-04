from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from database.models.content.voice import Voice
from database.operations import BaseRepository


class VoiceRepository(BaseRepository[Voice]):
    def __init__(self, db):
        super().__init__(Voice, db)

    async def available(self) -> list[Voice]:
        result = await self.db.execute(
            select(Voice).where(Voice.active.is_(True)).order_by(Voice.name)
        )
        return list(result.scalars().all())

    async def find_available(self, name: str) -> Voice | None:
        result = await self.db.execute(
            select(Voice).where(Voice.name == name, Voice.active.is_(True))
        )
        return result.scalar_one_or_none()

    async def sync(self, entries: list[dict]) -> None:
        # One transaction: readers see either the old catalog or the new one.
        # Concurrent application workers serialize startup reconciliation.
        from sqlalchemy import text
        await self.db.execute(text("SELECT pg_advisory_xact_lock(784630918234)"))
        for entry in entries:
            statement = insert(Voice).values(**entry, active=True)
            await self.db.execute(statement.on_conflict_do_update(
                index_elements=[Voice.name],
                set_={**entry, "active": True},
            ))
        names = [entry["name"] for entry in entries]
        await self.db.execute(
            update(Voice).where(Voice.name.not_in(names)).values(active=False)
        )
        await self.db.commit()
