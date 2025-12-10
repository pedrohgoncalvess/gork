from typing import Optional

from database import PgConnection
from database.models.manager import Model, Interaction, Command
from database.operations.manager import ModelRepository, InteractionRepository, CommandRepository
from external import make_request_openrouter
from external.evolution import download_media


async def describe_image(user_id: int, user_message: str, webhook_event: dict, group_id: Optional[int] = None, for_embeddings: bool = False) -> tuple[str, bytes]:
    event_data = webhook_event["data"]
    message_id = event_data["key"]["id"]
    async with PgConnection() as db:
        model_repo = ModelRepository(Model, db)
        default_audio_model = await model_repo.get_default_audio_model()

        message_data = event_data["message"]
        system = (
            "Discreva essa imagem em algumas palavras. Utilize no máximo 4-5 frases." if not for_embeddings
            else "Discreva essa imagem usando palavras pontuais que descrevem bem. Leve em consideração que essas palavras vão ser usadas pra gerar embeddings da imagem."
        )

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

        req = make_request_openrouter(payload)

        resume = req["choices"][0]["message"]["content"]

        command_repo = CommandRepository(Command, db)
        new_command = await command_repo.create_command(
            command="describe",
            user_id=user_id,
            group_id=group_id,
        )

        interaction_repo = InteractionRepository(Interaction, db)
        _ = await interaction_repo.create_interaction(
            model_id=default_audio_model.id,
            user_id=user_id,
            command_id=new_command.id,
            user_prompt=user_message,
            response=resume,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"],
            group_id=group_id,
            system_behavior=system
        )

        return resume, image_base64
