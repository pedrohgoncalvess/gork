import asyncio
import base64
import io
import subprocess
import wave

from database import PgConnection
from database.operations.content.voice import VoiceRepository
from database.operations.manager import AgentRepository, ModelConversationRepository
from external.openrouter import generate_speech_audio
from voices.catalog import VoiceSelectionError, extract_reference, reference_path, voice_name


async def clone_voice(
    text: str, voice: str, *, user_id: int, group_id: int | None = None,
    language: str = "pt",
) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Voice cloning requires non-empty text.")
    if not isinstance(voice, str) or not voice_name(voice):
        raise VoiceSelectionError("Informe a voz. Ex: !audio :voice=bolsonaro Olá!")
    if language not in {"pt", "en", "es"}:
        raise ValueError("Unsupported speech language.")
    async with PgConnection() as db:
        selected = await VoiceRepository(db).find_available(voice_name(voice))
        if selected is None:
            raise VoiceSelectionError("Voz indisponível. Consulte as vozes em !help.")
        agent = await AgentRepository(db).find_by_name("voice-cloning")
        if agent is None:
            raise RuntimeError("Voice cloning agent is not configured. Run init_agents.")
        model = await ModelConversationRepository(db).resolve_agent_model(
            agent, user_id=user_id, group_id=group_id,
        )
        if model is None:
            raise RuntimeError("Voice cloning model is not configured.")
        model_id = model.openrouter_id
        file_path = selected.file_path
        start, duration = selected.start_seconds, selected.duration_seconds
    try:
        path = reference_path(file_path)
        reference = await asyncio.to_thread(extract_reference, path, start, duration)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise VoiceSelectionError("A referência desta voz não está disponível. Consulte !help.") from error
    payload = {
        "model": model_id,
        "input": text.strip(),
        "response_format": "pcm",
        "input_references": [{
            "type": "input_audio",
            "input_audio": {"data": "data:audio/wav;base64," + base64.b64encode(reference).decode("ascii")},
        }],
        "provider": {"options": {"heygen": {"language": language}}},
    }
    audio = await generate_speech_audio(payload)
    if not audio.data or len(audio.data) % (2 * audio.channels):
        raise RuntimeError("OpenRouter returned truncated PCM16 audio.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(audio.channels)
        output.setsampwidth(2)
        output.setframerate(audio.sample_rate)
        output.writeframes(audio.data)
    return base64.b64encode(buffer.getvalue()).decode("ascii")
