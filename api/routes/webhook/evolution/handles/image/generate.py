import base64
from io import BytesIO
from typing import Optional

from PIL import Image

from database import PgConnection
from database.models.base import User
from database.models.manager import Command, Interaction
from database.models.content import Message
from database.operations.base import UserRepository
from database.operations.content import MessageRepository
from database.operations.manager import (
    AgentRepository,
    CommandRepository,
    InteractionRepository,
    ModelConversationRepository,
)
from external import completions
from external.evolution import download_media
from s3 import S3Client
from services import get_mentions_from_content
from utils import INSTANCE_NUMBER


async def generate_image(
        user_id: int,
        db_message: Message,
        action_params: Optional[dict] = None,
) -> tuple[str, bool]:
    mention_photo: list[tuple[str, User]] = []
    
    async with PgConnection() as db:
        agent_repo = AgentRepository(db)
        user_repo = UserRepository(db)
        message_repo = MessageRepository(db)
        model_conversation_repo = ModelConversationRepository(db)
        command_repo = CommandRepository(Command, db)

        modify_image_agent = await agent_repo.find_by_name("modify-image")
        if not modify_image_agent:
            return "Agente de imagem não configurado.", True

        image_system_prompt = modify_image_agent.prompt

        gork_user = await user_repo.find_by_phone_or_id(INSTANCE_NUMBER)
        gork_id = gork_user.id if gork_user else None

        raw_user_message = ""
        if action_params and action_params.get("prompt"):
            raw_user_message = str(action_params.get("prompt"))
        elif db_message and db_message.content:
            raw_user_message = db_message.content

        if gork_user:
            user_message = (
                raw_user_message
                .replace(f"@{gork_user.phone_number}@s.whatsapp.net", "")
                .replace(f"{gork_user.src_id}@lid", "")
                .replace(f"@{gork_user.src_id}", "")
            )
        else:
            user_message = raw_user_message

        # Fetch explicitly mentioned users
        mentions = await get_mentions_from_content(db_message, db) if db_message else []

        # Also support mentions passed in action_params
        if action_params and action_params.get("mentioned_users"):
            for u_id in action_params.get("mentioned_users", []):
                u_obj = None
                if isinstance(u_id, int):
                    u_obj = await user_repo.find_by_id(u_id)
                else:
                    try:
                        u_obj = await user_repo.find_by_id(int(u_id))
                    except (ValueError, TypeError):
                        u_obj = await user_repo.find_by_phone_or_id(str(u_id))
                if u_obj and all(m.id != u_obj.id for m in mentions):
                    mentions.append(u_obj)

        # Quoted message handling
        quoted_message = await message_repo.find_by_id(db_message.quoted_message_id) if db_message and db_message.quoted_message_id else None

        # Automatically include sender of quoted_message in mentions if available and not Gork
        if quoted_message and quoted_message.user_id:
            if gork_id is None or quoted_message.user_id != gork_id:
                quoted_user = await user_repo.find_by_id(quoted_message.user_id)
                if quoted_user and all(m.id != quoted_user.id for m in mentions):
                    mentions.append(quoted_user)

        s3_client = S3Client()
        await s3_client.connect()
        if mentions:
            for mention in mentions:
                if gork_user and mention.phone_number == gork_user.phone_number:
                    continue
                if mention and mention.profile_pic_path:
                    try:
                        photo_base64 = await s3_client.get_image_base64("whatsapp", mention.profile_pic_path)
                        if photo_base64:
                            mention_photo.append((photo_base64, mention))
                    except Exception:
                        pass

        new_command = await command_repo.create_command(
            command="image",
            user_id=user_id,
            group_id=db_message.group_id if db_message else None,
        )

        interaction_repo = InteractionRepository(Interaction, db)

        image_model = await model_conversation_repo.resolve_agent_model(
            modify_image_agent,
            user_id=user_id,
            group_id=db_message.group_id if db_message else None,
        )
        if not image_model:
            return "Modelo de imagem não configurado.", True

        # Collect images from the message itself and from the quoted message
        message_image_base64 = None
        quoted_image_base64 = None

        if db_message and db_message.message_id:
            try:
                res, _ = await download_media(db_message.message_id)
                if res:
                    message_image_base64 = res
            except Exception:
                message_image_base64 = None

        if quoted_message and quoted_message.message_id:
            try:
                res, _ = await download_media(quoted_message.message_id)
                if res:
                    quoted_image_base64 = res
            except Exception:
                quoted_image_base64 = None

        # Determine which is the "principal" image:
        # - If the message itself has an image, it's the principal
        # - Otherwise, the quoted image becomes the principal
        if message_image_base64:
            primary_image_base64 = message_image_base64
            secondary_image_base64 = quoted_image_base64
        else:
            primary_image_base64 = quoted_image_base64
            secondary_image_base64 = None

        photo_context = ""
        if mention_photo:
            for idx, (_, us) in enumerate(mention_photo, start=1):
                offset = 1
                if primary_image_base64:
                    offset += 1
                if secondary_image_base64:
                    offset += 1
                idx = idx + offset - 1
                user_message = user_message.replace(f"@{us.phone_number}@s.whatsapp.net", us.name or "Usuário").replace(f"{us.src_id}@lid", us.name or "Usuário").replace(f"@{us.src_id}", us.name or "Usuário")
                photo_context = f"{photo_context}Foto [{idx}]: É a pessoa: {us.name or 'Usuário'}\n"

        base64_context = ""
        if primary_image_base64 and secondary_image_base64:
            base64_context = (
                "A primeira foto é chamada de 'principal'. A segunda foto é uma imagem de referência/contexto adicional. "
                "Leve ambas em consideração quando analisar a requisição final do usuario."
            )
        elif primary_image_base64:
            base64_context = (
                "A primeira foto é chamada de 'principal'. Leve isso em consideração quando analisar a requisição final do usuario."
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

        if primary_image_base64:
            data_url = f"data:image/jpeg;base64,{primary_image_base64}"
            messages_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": data_url
                    }
                }
            )

        if secondary_image_base64:
            data_url = f"data:image/jpeg;base64,{secondary_image_base64}"
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
            "model": image_model.openrouter_id,
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
                    model_id=image_model.id,
                    user_id=user_id,
                    command_id=new_command.id,
                    user_prompt=user_message,
                    response=None,
                    input_tokens=req["usage"]["prompt_tokens"],
                    output_tokens=None,
                    group_id=db_message.group_id if db_message else None
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
            model_id=image_model.id,
            user_id=user_id,
            command_id=new_command.id,
            user_prompt=user_message,
            response=webp_base64,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"],
            group_id=db_message.group_id if db_message else None
        )

        return webp_base64, False
