import io
import re
import os
import wave
import base64
from datetime import datetime

from piper import SynthesisConfig, PiperVoice
from utils import project_root


async def text_to_speech(text: str, rate: float = 1.0, english: bool = False) -> str:
    syn_config = SynthesisConfig(
        volume=1.0,
        length_scale=1.0 / rate,
        noise_scale=0.667,
        normalize_audio=True,
    )

    if not english:
        voice = PiperVoice.load(f"{project_root}/tts/models/pt_BR-faber-medium.onnx")
    else:
        voice = PiperVoice.load(f"{project_root}/tts/models/en_US-ryan-high.onnx")

    wav_buffer = io.BytesIO()

    emoji_pattern = re.compile(
        "["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        u"\U0001F900-\U0001F9FF"
        u"\U0001FA70-\U0001FAFF"
        u"\U00002700-\U000027BF"
        u"\U0000FE00-\U0000FE0F"
        u"\U0001F018-\U0001F270"
        u"\U0001F600-\U0001F636"
        "]+"
    )

    tt_message = emoji_pattern.sub("", text)
    tt_message = re.sub(r"\s+", " ", tt_message).strip()

    with wave.open(wav_buffer, "wb") as wav_file:
        voice.synthesize_wav(tt_message, wav_file, syn_config=syn_config)

    audio_bytes = wav_buffer.getvalue()

    folder = "./data/tts"
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = os.path.join(folder, f"{timestamp}.wav")

    with open(file_path, "wb") as f:
        f.write(audio_bytes)

    audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

    return audio_base64
