import base64
from io import BytesIO

from PIL import Image

from database import PgConnection
from database.models.manager import Model, Interaction, Command
from database.operations.manager import ModelRepository, InteractionRepository, CommandRepository
from external import make_request_openrouter
from external.evolution import download_media


async def generate_image(user_id: int, user_message: str, webhook_event: dict, group_id: int = None) -> tuple[str, bool]:
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]
    async with PgConnection() as db:
        model_repo = ModelRepository(Model, db)
        default_image_model = await model_repo.get_default_image_model()

        message_data = event_data["message"]

        quoted_message_id = event_data.get("contextInfo", {}).get("stanzaId", "")
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

        result = make_request_openrouter(payload)

        if result.get("choices"):
            message = result["choices"][0]["message"]
            if message.get("images"):
                image = message["images"][0]["image_url"]["url"]
                if image.startswith("data:"):
                    image = image.split(",")[1]
            else:
                return "Não foi possível completar sua requisição. Tente novamente mais tarde.", True

        image_bytes = base64.b64decode(image)

        img = Image.open(BytesIO(image_bytes))

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        buffer.seek(0)
        webp_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        command_repo = CommandRepository(Command, db)
        new_command = await command_repo.create_command(
            command="!image",
            user_id=user_id,
            group_id=group_id,
        )

        interaction_repo = InteractionRepository(Interaction, db)
        first_iter = await interaction_repo.create_interaction(
            model_id=default_image_model.id,
            sender="user",
            command_id=new_command.id,
            content=f"User: {user_message}" + f"\n\nImage: {image}" if image else "",
            tokens=result["usage"]["prompt_tokens"]
        )

        _ = await interaction_repo.create_interaction(
            interaction_id=first_iter.id,
            model_id=default_image_model.id,
            sender="assistant",
            content=webp_base64,
            tokens=result["usage"]["completion_tokens"]
        )

        return webp_base64, False
