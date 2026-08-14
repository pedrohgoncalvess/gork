from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.manager import Interaction
from database.operations.content import MessageRepository
from database.operations.manager import InteractionRepository, ModelRepository
from external import embeddings
from log import logger


EMBEDDING_DIMENSION = 2560


def fit_embedding(embedding: list[float], dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    if len(embedding) == dimension:
        return embedding
    if len(embedding) > dimension:
        return embedding[:dimension]
    return embedding + [0.0] * (dimension - len(embedding))


async def generate_text_embeddings(
        text: str,
        message_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[int] = None,
        group_id: Optional[int] = None,
) -> list[float]:
    if not text or not text.strip():
        return []

    if not db:
        await logger.error("Embeddings", "GenerateTextEmbeddings", "No database session provided.")
        return []

    model_repo = ModelRepository(db)
    embedding_model = await model_repo.get_default_embedding_model()
    if not embedding_model:
        await logger.error("Embeddings", "GenerateTextEmbeddings", "Default embedding model not found.")
        return []

    try:
        embedding_json = await embeddings(text, embedding_model.openrouter_id)
    except Exception as e:
        await logger.error("Embeddings", "GenerateTextEmbeddings", f"Error generating embeddings: {e}")
        return []

    if not embedding_json or "data" not in embedding_json or not embedding_json["data"]:
        await logger.error("Embeddings", "GenerateTextEmbeddings", f"Unexpected embedding response format: {embedding_json}")
        return []

    resolved_user_id = user_id
    resolved_group_id = group_id

    if message_id:
        message_repo = MessageRepository(db)
        message = await message_repo.find_by_message_id(message_id)
        if message:
            if resolved_user_id is None:
                resolved_user_id = message.user_id
            if resolved_group_id is None:
                resolved_group_id = message.group_id

    if resolved_user_id:
        try:
            interaction_repo = InteractionRepository(Interaction, db)
            usage = embedding_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens)
            _ = await interaction_repo.create_interaction(
                model_id=embedding_model.id,
                user_id=resolved_user_id,
                group_id=resolved_group_id,
                user_prompt=text,
                input_tokens=prompt_tokens,
                output_tokens=max(0, total_tokens - prompt_tokens),
            )
        except Exception as e:
            await logger.warning("Embeddings", "GenerateTextEmbeddings", f"Failed to record interaction: {e}")

    raw_embedding = embedding_json["data"][0]["embedding"]
    return fit_embedding(raw_embedding)

