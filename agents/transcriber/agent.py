import base64
import json
from typing import Optional

from agents.transcriber.parser import audio_format, parse_transcription
from database import PgConnection
from database.models.manager import Command, Interaction
from database.operations.manager import AgentRepository, CommandRepository, InteractionRepository, ModelConversationRepository
from external import completions
from external.waha import download_media

async def transcribe_audio(webhook_data:dict, user_id: int, group_id: Optional[int], command: bool = False) -> str:
    async with PgConnection() as db:
        agent_repo = AgentRepository(db)
        model_conversation_repo = ModelConversationRepository(db)

        transcriber_agent = await agent_repo.find_by_name("transcriber")
        if not transcriber_agent:
            return ""

        audio_model = await model_conversation_repo.resolve_agent_model(
            transcriber_agent,
            user_id=user_id,
            group_id=group_id,
        )
        if not audio_model:
            return ""

        event_data = webhook_data["data"]
        context_info = event_data.get("contextInfo", {}) if event_data.get("contextInfo") is not None else {}

        audio_message = event_data.get("message", {}).get("audioMessage")
        if audio_message:
            message_id = event_data["key"]["id"]
        else:
            message_id = context_info.get("stanzaId")
            if not message_id:
                message_id = (
                    event_data.get("message", {})
                    .get("ephemeralMessage", {})
                    .get("message", {})
                    .get("extendedTextMessage", {})
                    .get("contextInfo", {})
                    .get("stanzaId")
                )
        base64_audio, filename = await download_media(message_id)
        audio_bytes = base64.b64decode(base64_audio, validate=True)
        format_name = audio_format(audio_bytes, filename)

        payload = {
            "model": audio_model.openrouter_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": transcriber_agent.prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": base64_audio,
                                "format": format_name
                            }
                        }
                    ]
                }
            ]
        }

        if transcriber_agent.response_format:
            try:
                payload["response_format"] = json.loads(transcriber_agent.response_format)
            except Exception:
                pass

        req = await completions(payload)
        resp = req["choices"][0]["message"]["content"]
        resp = parse_transcription(resp, bool(transcriber_agent.response_format))

        if command:
            command_repo = CommandRepository(Command, db)
            new_command = await command_repo.create_command(
                "transcribe",
                user_id,
                group_id=group_id,
            )
        else:
            new_command = None

        interaction_repo = InteractionRepository(Interaction, db)
        _ = await interaction_repo.create_interaction(
            model_id=audio_model.id,
            user_id=user_id,
            agent_id=transcriber_agent.id,
            command_id=new_command.id if new_command else None,
            user_prompt=base64_audio,
            response=resp,
            group_id=group_id,
            input_tokens=req["usage"]["prompt_tokens"],
            output_tokens=req["usage"]["completion_tokens"]
        )

        return resp
