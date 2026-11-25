"""Describe short videos and animations without publishing their contents."""

import asyncio
import base64
import json
import math
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from database.models.manager import Interaction
from database.operations.manager import AgentRepository, InteractionRepository, ModelConversationRepository
from external import completions


MAX_VIDEO_SECONDS = 60
MAX_VIDEO_BYTES = 20 * 1024 * 1024


def is_animation(data: bytes) -> bool:
    try:
        with Image.open(BytesIO(data)) as image:
            return bool(getattr(image, "is_animated", False))
    except (OSError, ValueError):
        return False


def prepare_video(data: bytes) -> bytes | None:
    """Validate duration before inference; convert GIF/WebP to a single MP4 play."""
    if not data or len(data) > MAX_VIDEO_BYTES:
        return None
    with tempfile.TemporaryDirectory(prefix="gork-describe-") as directory:
        source = Path(directory) / "source"
        source.write_bytes(data)
        if is_animation(data):
            with Image.open(BytesIO(data)) as image:
                total_ms = 0
                for frame in range(image.n_frames):
                    image.seek(frame)
                    image.load()
                    total_ms += max(image.info.get("duration", 100), 10)
                durations = [total_ms / 1000]
        else:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=duration,codec_type",
                 "-of", "json", str(source)],
                check=True, capture_output=True, timeout=15,
            )
            metadata = json.loads(probe.stdout)
            if not any(stream.get("codec_type") == "video" for stream in metadata.get("streams", [])):
                return None
            durations = [metadata.get("format", {}).get("duration")]
            durations.extend(stream.get("duration") for stream in metadata.get("streams", []))
        known = [float(value) for value in durations if value not in (None, "N/A")]
        if not known or any(not math.isfinite(value) for value in known):
            return None
        duration = max(known)
        if not 0 < duration <= MAX_VIDEO_SECONDS:
            return None
        # Decode animated images with Pillow: FFmpeg builds vary in WebP support.
        try:
            with Image.open(BytesIO(data)) as image:
                if getattr(image, "is_animated", False):
                    for frame in range(image.n_frames):
                        image.seek(frame)
                        picture = image.convert("RGB")
                        picture.thumbnail((512, 512))
                        picture.save(Path(directory) / f"frame-{frame:05d}.png")
                    manifest = Path(directory) / "frames.txt"
                    lines = []
                    for frame in range(image.n_frames):
                        image.seek(frame)
                        image.load()
                        lines.extend([f"file 'frame-{frame:05d}.png'", f"duration {max(image.info.get('duration', 100), 10) / 1000}"])
                    lines.append(f"file 'frame-{image.n_frames - 1:05d}.png'")
                    manifest.write_text("\n".join(lines), encoding="utf-8")
                    source = manifest
        except (OSError, ValueError):
            pass
        output = Path(directory) / "video.mp4"
        input_options = ["-f", "concat", "-safe", "0"] if source.suffix == ".txt" else []
        subprocess.run(
            ["ffmpeg", "-v", "error", *input_options, "-i", str(source),
             "-t", str(MAX_VIDEO_SECONDS), "-vf",
             "scale=512:512:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
             "-y", str(output)],
            check=True, capture_output=True, timeout=90,
        )
        result = output.read_bytes()
        return result if len(result) <= MAX_VIDEO_BYTES else None


async def describe_video(db, user_id, message_id, data, group_id=None) -> str:
    from services.agent_settings import apply_prompt_setting

    video = await asyncio.to_thread(prepare_video, data)
    if not video:
        return ""
    agent = await AgentRepository(db).find_by_name("describe-video")
    if not agent:
        return ""
    model = await ModelConversationRepository(db).resolve_agent_model(
        agent, user_id=user_id, group_id=group_id,
    )
    if not model:
        return ""
    payload = {
        "model": model.openrouter_id,
        "max_tokens": 400,
        "messages": [
            {"role": "system", "content": agent.prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "Descreva este vídeo para busca semântica."},
                {"type": "video_url", "video_url": {"url": "data:video/mp4;base64," + base64.b64encode(video).decode()}},
            ]},
        ],
    }
    apply_prompt_setting(payload, agent)
    response = await completions(payload)
    description = (response["choices"][0]["message"].get("content") or "").strip()
    usage = response.get("usage", {})
    await InteractionRepository(Interaction, db).create_interaction(
        model_id=model.id, user_id=user_id, group_id=group_id, agent_id=agent.id,
        user_prompt=f"Describe video: {message_id}", response=description,
        input_tokens=usage.get("prompt_tokens", 0), output_tokens=usage.get("completion_tokens", 0),
    )
    return description
