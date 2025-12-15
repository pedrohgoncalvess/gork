import base64
from io import BytesIO
from typing import Optional

import soundfile as sf

from database import PgConnection
from database.models.manager import Interaction, Model, Agent, Command
from database.operations.manager import InteractionRepository, ModelRepository, AgentRepository, CommandRepository
from external import make_request_openrouter
from external.evolution import download_media


async def transcribe_audio(webhook_data:dict, user_id: int, group_id: Optional[int], command: bool = False) -> str:
    async with PgConnection() as db:
        model_repo = ModelRepository(Model, db)
        agent_repo = AgentRepository(Agent, db)

        transcriber_agent = await agent_repo.find_by_name("transcriber")
        audio_model = await model_repo.get_default_audio_model()

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
        audio_base64, _ = await download_media(message_id)
        audio_bytes = base64.b64decode(audio_base64)
        audio_data, sample_rate = sf.read(BytesIO(audio_bytes))

        wav_buffer = BytesIO()
        sf.write(wav_buffer, audio_data, sample_rate, format='WAV')
        wav_buffer.seek(0)
        wav_bytes = wav_buffer.read()

        base64_audio = base64.b64encode(wav_bytes).decode("utf-8")

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
                                "format": "wav"
                            }
                        }
                    ]
                }
            ]
        }

        req = await make_request_openrouter(payload)
        resp = req["choices"][0]["message"]["content"]

        if command:
            command_repo = CommandRepository(Command, db)
            new_command = await command_repo.create_command(
                "transcribe",
                user_id
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