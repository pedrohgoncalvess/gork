from datetime import datetime, timezone

from sqlalchemy import and_, case, func, or_, select

from database.models.manager import DisabledCommand
from database.operations import BaseRepository


COMMAND_ALIASES = {
    "consumption": "usage",
    "english": "audio",
    "generate_sticker": "sticker",
    "list": "favorite",
    "message": "interaction",
    "remove": "favorite",
    "send_audio": "audio",
    "send_image": "image",
    "send_video": "video",
    "web_search": "search",
}


def normalize_command(command: str | None) -> str:
    normalized = (command or "interaction").strip().lower().lstrip("!")
    return COMMAND_ALIASES.get(normalized, normalized)


class DisabledCommandRepository(BaseRepository[DisabledCommand]):
    def __init__(self, db):
        super().__init__(DisabledCommand, db)

    async def find_active(
        self,
        command: str,
        user_id: int,
        group_id: int | None,
    ) -> DisabledCommand | None:
        now = datetime.now(timezone.utc)
        normalized = normalize_command(command)
        stored_command = func.lower(func.ltrim(DisabledCommand.command, "!"))

        scope_filters = [
            or_(DisabledCommand.user_id.is_(None), DisabledCommand.user_id == user_id),
        ]
        if group_id is None:
            scope_filters.append(DisabledCommand.group_id.is_(None))
        else:
            scope_filters.append(
                or_(DisabledCommand.group_id.is_(None), DisabledCommand.group_id == group_id)
            )

        specificity = (
            case((DisabledCommand.user_id.is_not(None), 1), else_=0)
            + case((DisabledCommand.group_id.is_not(None), 1), else_=0)
        )
        result = await self.db.execute(
            select(DisabledCommand)
            .where(
                stored_command == normalized,
                DisabledCommand.deleted_at.is_(None),
                or_(
                    DisabledCommand.disabled_until.is_(None),
                    DisabledCommand.disabled_until > now,
                ),
                and_(*scope_filters),
            )
            .order_by(specificity.desc(), DisabledCommand.inserted_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def disable(
        self,
        command: str,
        user_id: int | None = None,
        group_id: int | None = None,
        message: str = "Este comando está temporariamente desativado.",
        disabled_until: datetime | None = None,
    ) -> DisabledCommand:
        return await self.insert(
            DisabledCommand(
                command=normalize_command(command),
                user_id=user_id,
                group_id=group_id,
                message=message,
                disabled_until=disabled_until,
            )
        )
