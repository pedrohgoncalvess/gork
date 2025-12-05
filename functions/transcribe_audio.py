import base64
from io import BytesIO

import soundfile as sf

from database import PgConnection
from database.models.manager import Interaction, Model, Agent
from database.operations.manager import InteractionRepository, ModelRepository, AgentRepository
from external import make_request_openrouter
from external.evolution import download_media


async def transcribe_audio(webhook_data:dict) -> str:
    async with PgConnection() as db:
        model_repo = ModelRepository(Model, db)
        agent_repo = AgentRepository(Agent, db)

        transcriber_agent = await agent_repo.find_by_name("transcriber")
        audio_model = await model_repo.get_default_audio_model()

        event_data = webhook_data["data"]
        quoted_message_id = event_data.get("contextInfo", {}).get("stanzaId")
        if not quoted_message_id:
            quoted_message_id = (
                event_data.get("message", {})
                .get("ephemeralMessage", {})
                .get("message", {})
                .get("extendedTextMessage", {})
                .get("contextInfo", {})
                .get("stanzaId")
            )
        audio_base64 = await download_media(quoted_message_id)
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

        req = make_request_openrouter(payload)
        resp = req["choices"][0]["message"]["content"]

        interaction_repo = InteractionRepository(Interaction, db)
        first_interac = await interaction_repo.create_interaction(  # TODO: compress in just one interaction in the dat
            model_id = audio_model.id,
            sender = "user",
            agent_id = transcriber_agent.id,
            content = f"System: {transcriber_agent.prompt}\n\nUser: {base64_audio}",
            tokens = req["usage"]["prompt_tokens"]
        )

        _ = await interaction_repo.create_interaction(
            model_id=audio_model.id,
            sender="assistant",
            agent_id=transcriber_agent.id,
            content=resp,
            tokens=req["usage"]["prompt_tokens"],
            interaction_id=first_interac.id
        )

        return resp