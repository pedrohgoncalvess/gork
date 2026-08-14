import redis.asyncio as redis

from log import logger
from utils import get_env_var


AUDIO_ACTION_COOLDOWN_SECONDS = 180
_REDIS_CLIENT: redis.Redis | None = None


def _client() -> redis.Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is None:
        redis_url = get_env_var("REDIS_URL") or "redis://localhost:6379/0"
        _REDIS_CLIENT = redis.from_url(redis_url, decode_responses=True)
    return _REDIS_CLIENT


async def reserve_audio_action(scope: str) -> bool:
    """Reserve the audio slot for a chat, returning False during its cooldown."""
    try:
        key = f"gork:audio-action:cooldown:{scope}"
        return bool(
            await _client().set(
                key,
                "1",
                nx=True,
                ex=AUDIO_ACTION_COOLDOWN_SECONDS,
            )
        )
    except Exception as error:
        # An unavailable rate limiter must not prevent the bot from replying.
        await logger.error("ActionRateLimiter", "AudioCooldownError", str(error))
        return True
