import re
from typing import Optional

from agents.transcriber.agent import transcribe_audio
from external.waha import send_message
from services.params import PARAM_DEFAULTS


def clean_audio_text(text: str) -> str:
    """Remove command syntax without rewriting the words to be spoken."""
    # Remove parameter values too, including quoted values containing spaces.
    value = r'''(?:"[^"]*"|'[^']*'|[^\s!@:][^\s]*)'''
    text = re.sub(
        rf"(?<!\S):[\w-]+={value}", "", text, flags=re.IGNORECASE,
    )
    flags = "|".join(re.escape(key) for key in PARAM_DEFAULTS)
    text = re.sub(
        rf"(?<!\S):(?!(?:{flags})(?=\s|$))[\w-]+(?=\s|$)(?:[ \t]+{value})?",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"(?<!\S):(?:{flags})(?:[ \t]+(?:true|false|t|f|1|0)(?=\s|$))?(?=\s|$)",
        "", text, flags=re.IGNORECASE,
    )
    text = re.sub(r"(?<!\S):[\w-]+(?=\s|$)", "", text)
    text = re.sub(r"(?<!\S)![\w-]+\b", "", text)
    text = re.sub(r"(?<!\S)@[^\s,;!?]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


async def handle_audio_command(
    conversation, remote_id, user, db_message, db, scheduler, context, group_id=None,
):
    # Reuse permissions, delivery and synthesis-error handling.
    from api.routes.webhook.waha.handles.chat import _dispatch_action

    text = clean_audio_text(conversation)
    if not text:
        await send_message(
            remote_id, "Informe o texto para gerar o áudio. Ex: !audio Olá, tudo bem?",
            db_message.message_id,
        )
        return
    language = "en" if re.search(r"(?<!\S)!english(?=\s|$)", conversation, re.IGNORECASE) else "pt"
    parameters = {"text": text, "language": language}
    voice = re.search(
        r'''(?<!\S):voice(?:=|[ \t]+)(?:"([^"]+)"|'([^']+)'|([^\s]+))''',
        conversation, re.IGNORECASE,
    )
    if voice:
        parameters["voice"] = next(value for value in voice.groups() if value is not None)
    elif re.search(r"(?<!\S):voice(?:=|\s|$)", conversation, re.IGNORECASE):
        await send_message(remote_id, "Informe a voz. Ex: !audio :voice=bolsonaro Olá! Consulte !help.", db_message.message_id)
        return
    await _dispatch_action(
        action_type="audio", action={"parameters": parameters},
        remote_id=remote_id, user=user, db=db, db_message=db_message,
        scheduler=scheduler, context=context, group_id=group_id,
    )


async def handle_transcribe_command(
    remote_id: str, message_id: str, body: dict,
    user_id: int, group_id: Optional[int] = None,
):
    transcription = await transcribe_audio(body, user_id, group_id, command=True)
    await send_message(remote_id, f"_{transcription.strip()}_", message_id)
