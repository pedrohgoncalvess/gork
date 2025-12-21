from datetime import datetime
from typing import Optional
from uuid import uuid4
import base64

from database.models.base import Group, User
from database.models.content import Media, Message
from database.operations.base import GroupRepository, UserRepository
from database.operations.content import MediaRepository, MessageRepository
from embeddings import generate_text_embeddings
from external.evolution import download_media
from s3 import S3Client
from database import PgConnection
from database.models.manager import Model, Interaction, Command
from database.operations.manager import ModelRepository, InteractionRepository, CommandRepository
from external import completions
from services.message_context import verifiy_media
from utils import generate_random_name


async def describe_image(
        user_id: int, message: str,
        image_base64: bytes, group_id: Optional[int] = None,
        for_embeddings: bool = False) -> str:
    async with PgConnection() as db:
        model_repo = ModelRepository(Model, db)
        default_audio_model = await model_repo.get_default_audio_model()
        system = (
            "Descreva essa imagem em algumas palavras. Utilize no máximo 4-5 frases." if not for_embeddings
            else """Descreva esta imagem em 1-2 frases curtas, incluindo:
                    1. Tipo de conteúdo (screenshot, foto, arte)
                    2. Jogo/aplicativo (se reconhecível)
                    3. Elementos principais
                    4. Palavras-chave importantes
                    Exemplo: "Minecraft screenshot do jogo de video game mostrando o personagem olhando para vila com montanhas e o por do sol."
                    """
        )

        messages_content = [
            {
                "type": "text",
                "text": message
            }
        ]

        if image_base64:
            data_url = f"data:image/jpeg;base64,{image_base64}"
            messages_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                }
            )

        messages = [
            {
                "role": "system",
                "content": system
            },
            {
                "role": "user",
                "content": messages_content
            }
        ]

        payload = {
            "model": default_audio_model.openrouter_id,
            "messages": messages
            }

        req = await completions(payload)

        resume = req["choices"][0]["message"]["content"]

        command_repo = CommandRepository(Command, db)

        if for_embeddings:
            new_command = await command_repo.create_command(
                command="describe",
                user_id=user_id,
                group_id=group_id,
            )
            new_command_id = new_command.id
        else:
            new_command_id = None

        interaction_repo = InteractionRepository(Interaction, db)
        _ = await interaction_repo.create_interaction(
            model_id=default_audio_model.id,
            user_id=user_id,
            command_id=new_command_id,
            user_prompt=message,
            response=resume,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"],
            group_id=group_id,
            system_behavior=system
        )

        return resume


async def save_image(
        user_id: int,
        message_id: str,
        body: dict,
        image_base64: Optional[str] = None,
        group_id: Optional[int] = None,
) -> Media | None:
    medias = verifiy_media(body)
    if not medias.get("image_message") and not image_base64:
        return

    s3_conn = S3Client()
    _ = await s3_conn.connect()
    async with PgConnection() as db:
        if group_id is not None:
            group_repo = GroupRepository(Group, db)
            group = await group_repo.find_by_id(group_id)
            ext_id = group.ext_id
        else:
            user_repo = UserRepository(User, db)
            user = await user_repo.find_by_id(user_id)
            ext_id = user.ext_id

        if not image_base64:
            image_base64, name = await download_media(medias["image_message"])
        else:
            name = generate_random_name()

        description = await describe_image(user_id, message_id, image_base64, group_id, for_embeddings=True)

        decoded = base64.b64decode(image_base64)
        text_emb = await generate_text_embeddings(description, message_id, db)

        image_id = uuid4()
        path = f"{ext_id}/{datetime.now().strftime("%Y-%m-%d")}/{image_id}.png"
        _ = await s3_conn.upload_image(
            decoded,
            object_name = path
        )

        media_repo = MediaRepository(Media, db)
        message_repo = MessageRepository(Message, db)
        message = await message_repo.find_by_message_id(message_id)
        new_media = await media_repo.insert(
            Media(
                ext_id=image_id, name=name, message_id=message.id,
                bucket="whatsapp", path=path, format="png",
                description_embedding=text_emb, description=description
            )
        )

        return new_media