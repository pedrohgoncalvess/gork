from sqlalchemy.ext.asyncio import AsyncSession

from database.operations.base import BlackListRepository
from log import black_list_logger


BLACK_LIST_MESSAGE = "Desculpa, tive um problema interno. Tenta novamente."


async def is_feature_blocked(
    db: AsyncSession,
    user_id: int,
    feature: str,
) -> bool:
    return await BlackListRepository(db).blocks_feature(user_id, feature)


async def log_blocked_request(
    *,
    user_id: int,
    feature: str,
    group_id: int | None,
    message_id: str | None,
    source: str,
) -> None:
    """Registra bloqueios sem incluir conteúdo da mensagem nos logs."""
    try:
        await black_list_logger.info(
            "BlackList",
            "BlockedRequest",
            (
                f"source={source} user_id={user_id} group_id={group_id} "
                f"feature={feature or 'interaction'} message_id={message_id}"
            ),
        )
    except Exception:
        # O mecanismo de bloqueio não deve deixar de responder por uma falha de log.
        pass
