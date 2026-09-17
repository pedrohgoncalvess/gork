from sqlalchemy.ext.asyncio import AsyncSession

from database.operations.manager.disabled_command import DisabledCommandRepository


DEFAULT_DISABLED_COMMAND_MESSAGE = "Este comando está temporariamente desativado."


async def get_disabled_command_message(
    db: AsyncSession,
    command: str,
    user_id: int,
    group_id: int | None,
) -> str | None:
    disabled = await DisabledCommandRepository(db).find_active(
        command=command,
        user_id=user_id,
        group_id=group_id,
    )
    if disabled is None:
        return None
    return disabled.message or DEFAULT_DISABLED_COMMAND_MESSAGE
