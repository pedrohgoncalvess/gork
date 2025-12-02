import asyncio
from datetime import datetime, timedelta

import uvicorn
from fastapi import FastAPI, Request, HTTPException

from starlette import status
from fastapi import BackgroundTasks

from database import PgConnection, init_agents
from database.models.base import Group, WhiteList, User
from database.models.content import Message
from database.models.manager import Model
from database.operations.base.group import GroupRepository
from database.operations.base.user import UserRepository
from database.operations.base.white_list import WhiteListRepository
from database.operations.content.message import MessageRepository
from database.operations.manager.model import ModelRepository
from external import get_group_info, evolution_instance_key
from functions import get_resume_conversation, generic_conversation, generate_sticker
from functions.audio.transcribe_audio import transcribe_audio
from functions.web_search import web_search
from log import logger
from external.evolution import send_message, send_audio, send_sticker
from tts import text_to_speech


app = FastAPI()

COMMANDS = [
    ("@gork", "_[Sem comando]_ Interação genérica"),
    ("!help", "Mostra os comandos disponíveis. _[Ignora o restante da mensagem]_"),
    ("!audio", "Envia áudio como forma de resposta. _[Adicione !english para voz em inglês]_"),
    ("!resume", "Faz um resumo das últimas 30 mensagens. _[Ignora o restante da mensagem]_"),
    ("!search", "Faz uma pesquisa por termo na internet e retorna um resumo."),
    ("!model", "Mostra um modelo sendo utilizado."),
    ("!sticker", "Cria um sticker com base em uma imagem fornecida. _[Use | como separador de top/bottom]_"),
    ("!engligh", "")
]

@app.post("/webhook/evolution")
async def evolution_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
):
    try:
        body = await request.json()
    except Exception as e:
        await logger.error("Webhook", "Error reading body", str(e))
        return {"status": "error"}

    api_key = body.get("apikey")

    if api_key != evolution_instance_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    background_tasks.add_task(process_webhook, body)

    return {"status": "received"}


async def process_webhook(body: dict):
    async with PgConnection() as db:
        whitelist_repo = WhiteListRepository(WhiteList, db)
        user_repo = UserRepository(User, db)
        message_repo = MessageRepository(Message, db)
        group_repo = GroupRepository(Group, db)

        event_type = body.get("event")
        event_data = body.get("data")

        if event_type == "send.message":
            return

        if event_type == "messages.upsert":
            await logger.info("Request", body.get("instance"), body)
            remote_id = body.get("data", {}).get("key", {}).get("remoteJid", "")
            message_id = event_data["key"]["id"]
            contact_name = event_data["pushName"]

            message_data = event_data.get("message", {})

            if remote_id.endswith("@g.us"):
                group_jid = remote_id.replace("@g.us", "")
                contact_id = event_data["key"]["participant"].replace("@lid", "")

                created_at = datetime.fromtimestamp(event_data["messageTimestamp"])

                if created_at < (datetime.now() - timedelta(minutes=20)):
                    return

                user = await user_repo.find_or_create(
                    name=contact_name,
                    lid=contact_id
                )

                group = await group_repo.find_or_create(
                    group_jid=group_jid
                )

                if not group.name:
                    gp_infos = get_group_info(remote_id)
                    group = await group_repo.find_or_create(
                        group_jid=group_jid,
                        name=gp_infos["subject"],
                        description=gp_infos.get("desc"),
                    )

                is_whitelisted = await whitelist_repo.is_whitelisted(
                    sender_type="group",
                    sender_id=group.id
                )

                caption = message_data.get('imageMessage', {}).get('caption', '')
                conversation = caption if caption else message_data.get("conversation", "")

                if not conversation:
                    conversation = message_data.get("ephemeralMessage", {}).get("message", {}).get("extendedTextMessage", {}).get("text", "")

                _ = await message_repo.find_or_create(
                    message_id=event_data["key"]["id"],
                    sender_id=user.id,
                    group_id=group.id,
                    content=conversation,
                    created_at=datetime.fromtimestamp(event_data["messageTimestamp"])
                )

                if not is_whitelisted:
                    return

                if "@gork" not in conversation.lower():
                    return

                if conversation.lower().replace("!english", "") == "@gork":
                    audio_message = event_data.get("contextInfo", {}).get("quotedMessage", {}).get("audioMessage")
                    ephemeral_audio_message = (
                        event_data.get("message", {})
                        .get("ephemeralMessage", {})
                        .get("message", {})
                        .get("extendedTextMessage", {})
                        .get("contextInfo", {})
                        .get("quotedMessage", {})
                        .get("ephemeralMessage", {})
                        .get("message", {})
                        .get("audioMessage")
                    )
                    if audio_message or ephemeral_audio_message:
                        conversation = await transcribe_audio(body)
                        response_message = await generic_conversation(group.id, user.name, conversation)
                        language = response_message.get("language")
                        audio_base64 = await text_to_speech(response_message.get("text"), language)
                        await send_audio(remote_id, audio_base64, message_id)
                        return
                    else:
                        await send_message(remote_id, f"🤖 Robo do mito está pronto", message_id)
                        return

                treated_text = conversation.strip()
                for command, _ in COMMANDS:
                    treated_text = treated_text.replace(command, "")
                treated_text = treated_text.strip()

                if "!sticker" in conversation.lower():
                    webp_base64 = await generate_sticker(body, treated_text)
                    await send_sticker(remote_id, webp_base64)
                    return

                if "!help" in conversation.lower():
                    tt_messages = ["Comandos do Gork disponíveis."]
                    for command, desc in COMMANDS:
                        if desc:
                            tt_messages.append(
                                f"*{command}* - {desc}"
                            )
                    tt_commands = "\n".join(tt_messages)
                    final_message = f"{tt_commands}\n\nContribuite on https://github.com/pedrohgoncalvess/gork"
                    await send_message(remote_id, final_message, message_id)
                    return

                if "!model" in conversation.lower():
                    model_repo = ModelRepository(Model, db)
                    model = await model_repo.get_default_model()
                    await send_message(remote_id, f"Ta sendo usado o {model.name}.", message_id)
                    return

                if "!resume" in conversation.lower():
                    resume = await get_resume_conversation(user.id, group_id=group.id)
                    await send_message(remote_id, resume, message_id)
                    return

                if "!search" in conversation.lower():
                    search = await web_search(treated_text, remote_id)
                    await send_message(remote_id, search, message_id)
                    return

                response_message = await generic_conversation(group.id, user.name, treated_text)
                if "!audio" in conversation.lower():
                    audio_base64 = await text_to_speech(
                        response_message.get("text"),
                        language=response_message.get("language")
                    )
                    await send_audio(remote_id, audio_base64, message_id)
                    return

                model_repo = ModelRepository(Model, db)
                default_model = await model_repo.get_default_model()
                response_message = f"{response_message.get('text')}\n\n_{default_model.name}_"
                await send_message(remote_id, response_message, message_id)
                return

            elif remote_id.endswith(".net"):
                # TODO: Implement
                pass


if __name__ == "__main__":
    asyncio.run(init_agents())
    uvicorn.run(app, host="0.0.0.0", port=9001)