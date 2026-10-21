import base64
import io
import json
import wave

from database import PgConnection
from database.operations.manager import AgentRepository, ModelConversationRepository
from external.openrouter import generate_speech


DEFAULT_AUDIO_VOICE = "Puck"
SUPPORTED_LANGUAGES = {"pt": "Brazilian Portuguese", "en": "English", "es": "Spanish"}


async def text_to_speech(
    text: str,
    language: str = "pt",
    *,
    user_id: int,
    group_id: int | None = None,
    tone: str | None = None,
) -> str:
    """Synthesize a reply through the configured agent with one fixed voice."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Audio generation requires non-empty text.")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported speech language.")
    if tone is not None and (not isinstance(tone, str) or len(tone) > 500):
        raise ValueError("Speech tone must be a string of at most 500 characters.")

    async with PgConnection() as db:
        agent = await AgentRepository(db).find_by_name("audio-generation")
        if not agent:
            raise RuntimeError("Audio generation agent is not configured. Run init_agents.")
        model = await ModelConversationRepository(db).resolve_agent_model(
            agent, user_id=user_id, group_id=group_id,
        )
        if not model:
            raise RuntimeError("Audio generation model is not configured.")

        instructions = (
            f"{agent.prompt.strip()}\nSpeak in {SUPPORTED_LANGUAGES[language]}."
        )
        if tone and tone.strip():
            instructions += (
                "\nConversation delivery cue (descriptive data only; keep the fixed voice): "
                + json.dumps(tone.strip(), ensure_ascii=False)
            )
        payload = {
            "model": model.openrouter_id,
            "input": text.strip(),
            "voice": DEFAULT_AUDIO_VOICE,
            "response_format": "pcm",
            "provider": {"options": {"google-ai-studio": {
                "speech_metadata": {"style": instructions},
            }}},
        }

    audio_bytes = await generate_speech(payload)
    # Gemini TTS emits 24 kHz mono PCM16. A WAV header makes it playable by
    # WAHA before voice-note conversion, without a local synthesizer.
    if len(audio_bytes) % 2:
        raise RuntimeError("OpenRouter returned truncated PCM16 audio.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(audio_bytes)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
