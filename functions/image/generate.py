import asyncio
import base64
from io import BytesIO

from PIL import Image

from database import PgConnection
from database.models.manager import Model, Interaction, Command
from database.operations.manager import (
    ModelRepository, InteractionRepository, CommandRepository
)
from external import make_request_openrouter
from external.evolution import download_media
from services.save_image import materialize_image


async def generate_image(user_id: int, user_message: str, webhook_event: dict, group_id: int = None) -> tuple[str, bool]:
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]
    async with PgConnection() as db:
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
            image_base64 = await download_media(message_id)
        elif quoted_message_id:
            image_base64 = await download_media(quoted_message_id)
        else:
            image_base64 = None

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

        req = await make_request_openrouter(payload)

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

        webp_base64_bytes = base64.b64encode(buffer.getvalue())
        if group_id:
            asyncio.create_task(
                materialize_image(message_id, webp_base64_bytes, group_id=group_id)
            )
        else:
            asyncio.create_task(
                materialize_image(message_id, webp_base64_bytes, user_id=user_id)
            )
        return webp_base64, False
