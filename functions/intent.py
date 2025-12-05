from sqlalchemy.ext.asyncio import AsyncSession

from services import manage_interaction


async def classify_intent(message: str, db: AsyncSession, commands: list[tuple[str, str]]) -> tuple[str, bool]:
    if any(cmd in message.lower() for cmd, _ in commands if cmd.startswith("!")):
        return "explicit_command", False

    response = await manage_interaction(db, message, agent_name="intent-classifier")

    parts = [p.strip().lower() for p in response.split(",")]
    intent = parts[0]
    wants_audio = "audio" in parts

    valid_intents = [
        "remember", "search", "image", "sticker", "transcribe",
        "resume", "model", "help", "conversation"
    ]

    if intent not in valid_intents:
        intent = "conversation"

    return intent, wants_audio