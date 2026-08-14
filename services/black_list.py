from sqlalchemy.ext.asyncio import AsyncSession

from database.operations.base import BlackListRepository


BLACK_LIST_MESSAGE = "Desculpa, tive um problema interno. Tenta novamente."


async def is_feature_blocked(
    db: AsyncSession,
    user_id: int,
    feature: str,
) -> bool:
    return await BlackListRepository(db).blocks_feature(user_id, feature)
