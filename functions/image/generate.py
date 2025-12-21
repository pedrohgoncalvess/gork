import asyncio
import base64
import re
from io import BytesIO

from PIL import Image

from database import PgConnection
from database.models.base import User
from database.models.manager import Model, Interaction, Command
from database.operations.base import UserRepository
from database.operations.manager import (
    ModelRepository, InteractionRepository, CommandRepository
)
from external import completions
from external.evolution import download_media
from s3 import S3Client
from services import verifiy_media
from services.save_image import save_image
from utils import get_env_var


async def generate_image(
        user_id: int, user_message: str,
        webhook_event: dict, group_id: int = None
) -> tuple[str, bool]:
    message_context = verifiy_media(webhook_event)
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]
    user_message = re.sub(r'!\w{3,}', '', user_message)

    mention_photo: list[tuple[str, User]] = []
    async with PgConnection() as db:
        mentions = message_context.get("mentions")
        s3_client = S3Client()
        await s3_client.connect()
        if mentions is not None:
            user_repo = UserRepository(User, db)
            for mention in mentions:
                user_mentioned = await user_repo.find_by_phone_or_id(mention)
                if user_mentioned.name != get_env_var("EVOLUTION_INSTANCE_NAME"):
                    if user_mentioned is not None and user_mentioned.profile_pic_path is not None:
                        photo_base64 = await s3_client.get_image_base64("whatsapp", user_mentioned.profile_pic_path)
                        mention_photo.append((photo_base64, user_mentioned))

        model_repo = ModelRepository(Model, db)
        command_repo = CommandRepository(Command, db)
        new_command = await command_repo.create_command(
            command="image",
            user_id=user_id,
            group_id=group_id,
        )

        interaction_repo = InteractionRepository(Interaction, db)

        default_image_model = await model_repo.get_default_image_model()

        message_data = event_data["message"]

        context_info = event_data.get("contextInfo", {}) if event_data.get("contextInfo") is not None else {}
        quoted_message_id = context_info.get("stanzaId")
        if not quoted_message_id:
            quoted_message_id = (
                event_data.get("message", {})
                .get("ephemeralMessage", {})
                .get("message", {})
                .get("extendedTextMessage", {})
                .get("contextInfo", {})
                .get("stanzaId")
            )

        if message_data.get("imageMessage"):
            image_base64, _ = await download_media(message_id)
        elif quoted_message_id:
            image_base64, _ = await download_media(quoted_message_id)
        else:
            image_base64 = None

        photo_context = ""
        if mention_photo:
            for idx, (_, us) in enumerate(mention_photo, start=2):
                user_message = user_message.replace(f"@{us.phone_number}@s.whatsapp.net", us.name).replace(f"{us.src_id}@lid", us.name)
                photo_context = f"{photo_context}Foto [{idx}]:É a pessoa: {us.name}\n"

        user_message = user_message if not photo_context else f"{photo_context}\n\n{user_message}"
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

        asyncio.create_task(
            save_image(user_id, message_id, webhook_event, webp_base64, group_id)
        )
        return webp_base64, False
