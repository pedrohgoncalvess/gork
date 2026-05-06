import base64
from io import BytesIO

from PIL import Image

from database import PgConnection
from database.models.base import User
from database.models.manager import Command, Interaction
from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.manager import (
    CommandRepository, InteractionRepository, ModelRepository, AgentRepository
)
from external import completions
from external.evolution import download_media
from s3 import S3Client
from utils import get_env_var


async def generate_image(
        user_id: int, user_message: str,
        message_context: dict, db_message: Message,
        group_id: int = None
) -> tuple[str, bool]:
    mention_photo: list[tuple[str, User]] = []
    async with PgConnection() as db:
        agent_repo = AgentRepository(db)
        user_repo = UserRepository(db)

        modify_image_agent = await agent_repo.find_by_name("modify-image")
        image_system_prompt = modify_image_agent.prompt

        gork_user = await user_repo.find_by_phone_or_id(get_env_var("EVOLUTION_INSTANCE_NUMBER"))
        user_message = (
            user_message
            .replace(f"@{gork_user.phone_number}@s.whatsapp.net", "")
            .replace(f"{gork_user.src_id}@lid", "")
            .replace(f"@{gork_user.src_id}", "")
        )

        mentions = message_context.get("mentions")
        s3_client = S3Client()
        await s3_client.connect()
        if mentions is not None:

            for mention in mentions:
                user_mentioned = await user_repo.find_by_phone_or_id(mention)
                if user_mentioned.name != get_env_var("EVOLUTION_INSTANCE_NAME"):
                    if user_mentioned is not None and user_mentioned.profile_pic_path is not None:
                        photo_base64 = await s3_client.get_image_base64("whatsapp", user_mentioned.profile_pic_path)
                        mention_photo.append((photo_base64, user_mentioned))

        model_repo = ModelRepository(db)
        command_repo = CommandRepository(Command, db)
        new_command = await command_repo.create_command(
            command="image",
            user_id=user_id,
            group_id=group_id,
        )

        interaction_repo = InteractionRepository(Interaction, db)

        default_image_model = await model_repo.get_default_image_model()

        quoted_message_id = message_context.get("quoted_message")

        if message_context.get("image_quote"):
            image_base64, _ = await download_media(db_message.message_id)
        elif quoted_message_id:
            image_base64, _ = await download_media(quoted_message_id)
        else:
            image_base64 = None

        photo_context = ""
        if mention_photo:
            for idx, (_, us) in enumerate(mention_photo, start=1):
                idx = idx + 1 if image_base64 else idx
                user_message = user_message.replace(f"@{us.phone_number}@s.whatsapp.net", us.name).replace(f"{us.src_id}@lid", us.name).replace(f"@{us.src_id}", us.name)
                photo_context = f"{photo_context}Foto [{idx}]:É a pessoa: {us.name}\n"

        base64_context = (
            "A primeira foto é chamada de 'principal'. Leve isso em consideração quando analisar a requisição final do usuario."
            if image_base64 else ""
        )

        final_message = ""
        if base64_context:
            final_message = f"{base64_context}\n"
        if photo_context:
            final_message = f"{final_message}{photo_context}\n\n"

        user_message = f"{final_message}\n\n{user_message}"
        messages_content = [
            {
                "type": "text",
                "text": user_message
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

        if mention_photo:
            for photo, _ in mention_photo:
                data_url = f"data:image/jpeg;base64,{photo}"
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
                "content": [{"type": "text", "text": image_system_prompt}],
            },
            {
                "role": "user",
                "content": messages_content
            }
        ]

        payload = {
            "model": default_image_model.openrouter_id,
            "messages": messages
        }

        req = await completions(payload)

        if req.get("choices"):
            message = req["choices"][0]["message"]
            if message.get("images"):
                image = message["images"][0]["image_url"]["url"]
                if image.startswith("data:"):
                    image = image.split(",")[1]
            else:
                _ = await interaction_repo.create_interaction(
                    model_id=default_image_model.id,
                    user_id=user_id,
                    command_id=new_command.id,
                    user_prompt=user_message,
                    response=None,
                    input_tokens=req["usage"]["prompt_tokens"],
                    output_tokens=None,
                    group_id=group_id
                )
                return "Não foi possível completar sua requisição. Tente novamente mais tarde.", True

        image_bytes = base64.b64decode(image)

        img = Image.open(BytesIO(image_bytes))

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        buffer.seek(0)
        webp_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        _ = await interaction_repo.create_interaction(
            model_id=default_image_model.id,
            user_id=user_id,
            command_id=new_command.id,
            user_prompt=user_message,
            response=webp_base64,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"],
            group_id=group_id
        )

        return webp_base64, False
