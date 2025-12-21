from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content import Message
from database.models.manager import Model, Interaction
from database.operations.content import MessageRepository
from database.operations.manager import ModelRepository, InteractionRepository
from external import embeddings


async def generate_text_embeddings(text: str, message_id: str, db: AsyncSession) -> list[float]:
    message_repo = MessageRepository(Message, db)
    message = await message_repo.find_by_message_id(message_id)

    model_repo = ModelRepository(Model, db)
    embedding_model = await model_repo.get_default_embedding_model()

    embedding_json = await embeddings(text, embedding_model.openrouter_id)
    interaction_repo = InteractionRepository(Interaction, db)
    _ = await interaction_repo.create_interaction(
        model_id=embedding_model.id,
        user_id=message.user_id,
        group_id=message.group_id,
        user_prompt=text,
        input_tokens=embedding_json["usage"]["prompt_tokens"],
        output_tokens=(embedding_json["usage"]["total_tokens"] - embedding_json["usage"]["prompt_tokens"])
    )
    return embedding_json["data"][0]["embedding"]