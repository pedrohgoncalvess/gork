from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from services import manage_interaction


async def classify_intent(message: str, db: AsyncSession, commands: list[tuple[str, str]], medias: dict[str, str], user_id: int, group_id: Optional[int]) -> tuple[str, bool]:
    if any(cmd in message.lower() for cmd, _, _, _ in commands if cmd.startswith("!")):
        return "explicit_command", False

    medias = medias.keys()
    has_audio = "Sim" if "audio_message" in medias else "Não"
    has_image = "Sim" if "image_message" in medias else "Não"
    has_audio_quote = "Sim" if "audio_quote" in medias else "Não"
    has_image_quote = "Sim" if "image_quote" in medias else "Não"

    final_message = (
        f"\nMensagem: {message}:\n"
        f"Informações da última mensagem:\n"
        f"Mensagem de áudio: {has_audio}\n"
        f"Imagem anexada: {has_image}\n"
        f"Quote áudio: {has_audio_quote}\n"
        f"Quote imagem: {has_image_quote}\n"
    )

    response = await manage_interaction(db, final_message, agent_name="intent-classifier", user_id=user_id, group_id=group_id)

    parts = [p.strip().lower() for p in response.split(",")]
    intent = parts[0]
    wants_audio = "audio" in parts

    valid_intents = [
        "remember", "search", "image", "sticker", "transcribe",
        "resume", "model", "help", "conversation", "audio"
    ]

    if intent not in valid_intents:
        intent = "conversation"

    return intent, wants_audio