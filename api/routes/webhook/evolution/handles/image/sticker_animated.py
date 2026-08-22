import asyncio
import base64
import math
import os
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
from PIL import Image

from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.sticker_caption import add_caption_to_image
from api.routes.webhook.evolution.handles.image.sticker_filters import remove_color
from database.models.content import Message
from external.evolution import download_media
from utils import project_root


VIDEO_REMBG_FPS = 2
VIDEO_REMBG_SCALE = 320
VIDEO_REMBG_DURATION = 3
VIDEO_REMBG_MODEL = "u2netp"
VIDEO_CUT_MAX_DURATION = 7.0
STATIC_EFFECT_FPS = 15
STATIC_EFFECT_DURATION = 3
STATIC_EXPLOSION_FPS = 30
STATIC_STICKER_MAX_BYTES = 490_000
VIDEO_STICKER_MAX_BYTES = 350_000
NUCLEAR_BOMB_EFFECTS = {"nuclear-bomb", "nuclear_bomb"}
NUCLEAR_BOMB_GIF_URL = "https://media.giphy.com/media/CWn8Pu7ezdiiJ6dVgo/giphy.gif"
NUCLEAR_BOMB_START_PROGRESS = 0.35
NUCLEAR_BOMB_MAX_FRAME_RATIO = 0.72
NUCLEAR_BOMB_OPACITY = 0.78
EXPLOSION_GIF_URL = "https://media.giphy.com/media/1vZccDvoiwzCmv5OKZ/giphy.gif"
EXPLOSION_GIF_PATH = (
    Path(project_root) / "assets" / "image" / "actionvfx-explosion.gif"
)
EXPLOSION_MAX_FRAME_RATIO = 0.65
EXPLOSION_MAX_SOURCE_FRAMES = 60


def _parse_cut_timestamp(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None

    try:
        if ":" not in value:
            return max(float(value), 0.0)

        parts = value.split(":")
        if len(parts) != 2:
            return None

        minutes = float(parts[0] or 0)
        seconds = float(parts[1] or 0)
        return max(minutes * 60 + seconds, 0.0)
    except ValueError:
        return None


def _parse_cut_range(cut_spec) -> tuple[float, float] | None:
    if cut_spec is None:
        return None

    value = str(cut_spec).strip()
    if not value:
        return None

    if "-" not in value:
        start = _parse_cut_timestamp(value)
        if start is None:
            return None
        return start, VIDEO_CUT_MAX_DURATION

    start_raw, end_raw = value.split("-", 1)
    start = _parse_cut_timestamp(start_raw)
    end = _parse_cut_timestamp(end_raw)

    if start is None and end is None:
        return None
    if start is None:
        end = end or 0.0
        start = max(end - VIDEO_CUT_MAX_DURATION, 0.0)
        return start, min(max(end - start, 0.1), VIDEO_CUT_MAX_DURATION)
    if end is None:
        return start, VIDEO_CUT_MAX_DURATION
    if end < start:
        start, end = end, start

    duration = min(max(end - start + 1.0, 0.1), VIDEO_CUT_MAX_DURATION)
    return start, duration


async def _upload_to_tmpfile(gif_path: str) -> str:
    URL = "https://tmpfile.link/api/upload"
    async with httpx.AsyncClient() as client:
        with open(gif_path, "rb") as image:
            response = await client.post(
                URL,
                files={
                    "file": (gif_path, image, "image/gif")
                },
                timeout=30
            )
    response.raise_for_status()
    data = response.json()
    return data.get("downloadLink")


def _convert_to_rgb(frame: Image.Image) -> Image.Image:
    if frame.mode == 'RGB':
        return frame
    if frame.mode == 'RGBA':
        background = Image.new('RGB', frame.size, (255, 255, 255))
        background.paste(frame, mask=frame.split()[3])
        return background
    if frame.mode == 'P':
        frame_rgba = frame.convert('RGBA')
        background = Image.new('RGB', frame_rgba.size, (255, 255, 255))
        background.paste(frame_rgba, mask=frame_rgba.split()[3])
        return background
    return frame.convert('RGB')


def _resize_cover(frame: Image.Image, size: tuple) -> Image.Image:
    target_w, target_h = size
    orig_w, orig_h = frame.size
    scale = max(target_w / orig_w, target_h / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    frame = frame.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return frame.crop((left, top, left + target_w, top + target_h))


def _square_video_filter(size: int, fill: bool) -> str:
    if fill:
        return (
            f"scale={size}:{size}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={size}:{size}"
        )

    return (
        f"scale={size}:{size}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=white@0"
    )


def _apply_bulge_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                factor = math.pow(factor, 2) * intensity
                new_distance = distance * (1 + factor)
                if new_distance < max_radius:
                    angle = math.atan2(dy, dx)
                    src_x = int(center_x + new_distance * math.cos(angle))
                    src_y = int(center_y + new_distance * math.sin(angle))
                    if 0 <= src_x < width and 0 <= src_y < height:
                        new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_pinch_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                factor = math.pow(factor, 2) * intensity
                new_distance = distance * (1 - factor * 0.5)
                angle = math.atan2(dy, dx)
                src_x = int(center_x + new_distance * math.cos(angle))
                src_y = int(center_y + new_distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_swirl_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                rotation = factor * intensity * math.pi * 2
                angle = math.atan2(dy, dx) + rotation
                src_x = int(center_x + distance * math.cos(angle))
                src_y = int(center_y + distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_wave_effect(frame: Image.Image, intensity: float = 10) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    new_img = np.copy(img_array)
    for y in range(height):
        offset = int(intensity * math.sin(y * 0.1))
        for x in range(width):
            src_x = (x + offset) % width
            new_img[y, x] = img_array[y, src_x]
    return Image.fromarray(new_img)


def _apply_fisheye_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = min(center_x, center_y)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                norm_distance = distance / max_radius
                new_distance = max_radius * math.pow(norm_distance, 1 + intensity)
                angle = math.atan2(dy, dx)
                src_x = int(center_x + new_distance * math.cos(angle))
                src_y = int(center_y + new_distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_breathing_effect(frame: Image.Image, progress: float) -> Image.Image:
    intensity = math.sin(progress * math.pi * 2) * 0.3
    if intensity > 0:
        return _apply_bulge_effect(frame, intensity)
    else:
        return _apply_pinch_effect(frame, abs(intensity))


def _apply_rotation_effect(
        frame: Image.Image,
        progress: float,
        rotations: int = 1,
) -> Image.Image:
    angle = progress * 360 * max(1, rotations)
    fillcolor = (0, 0, 0, 0) if frame.mode == "RGBA" else (255, 255, 255)
    return frame.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor=fillcolor)


    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                factor = math.pow(factor, 2) * intensity
                new_distance = distance * (1 + factor)
                if new_distance < max_radius:
                    angle = math.atan2(dy, dx)
                    src_x = int(center_x + new_distance * math.cos(angle))
                    src_y = int(center_y + new_distance * math.sin(angle))
                    if 0 <= src_x < width and 0 <= src_y < height:
                        new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_pinch_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                factor = math.pow(factor, 2) * intensity
                new_distance = distance * (1 - factor * 0.5)
                angle = math.atan2(dy, dx)
                src_x = int(center_x + new_distance * math.cos(angle))
                src_y = int(center_y + new_distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_swirl_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                factor = 1.0 - (distance / max_radius)
                rotation = factor * intensity * math.pi * 2
                angle = math.atan2(dy, dx) + rotation
                src_x = int(center_x + distance * math.cos(angle))
                src_y = int(center_y + distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_wave_effect(frame: Image.Image, intensity: float = 10) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    new_img = np.copy(img_array)
    for y in range(height):
        offset = int(intensity * math.sin(y * 0.1))
        for x in range(width):
            src_x = (x + offset) % width
            new_img[y, x] = img_array[y, src_x]
    return Image.fromarray(new_img)


def _apply_fisheye_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]
    center_x, center_y = width // 2, height // 2
    max_radius = min(center_x, center_y)
    new_img = np.copy(img_array)
    for y in range(height):
        for x in range(width):
            dx = x - center_x
            dy = y - center_y
            distance = math.sqrt(dx ** 2 + dy ** 2)
            if distance < max_radius:
                norm_distance = distance / max_radius
                new_distance = max_radius * math.pow(norm_distance, 1 + intensity)
                angle = math.atan2(dy, dx)
                src_x = int(center_x + new_distance * math.cos(angle))
                src_y = int(center_y + new_distance * math.sin(angle))
                if 0 <= src_x < width and 0 <= src_y < height:
                    new_img[y, x] = img_array[src_y, src_x]
    return Image.fromarray(new_img)


def _apply_breathing_effect(frame: Image.Image, progress: float) -> Image.Image:
    intensity = math.sin(progress * math.pi * 2) * 0.3
    if intensity > 0:
        return _apply_bulge_effect(frame, intensity)
    else:
        return _apply_pinch_effect(frame, abs(intensity))


def _apply_rotation_effect(
        frame: Image.Image,
        progress: float,
        rotations: int = 1,
) -> Image.Image:
    angle = progress * 360 * max(1, rotations)
    fillcolor = (0, 0, 0, 0) if frame.mode == "RGBA" else (255, 255, 255)
    return frame.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor=fillcolor)


def _apply_nuclear_bomb_effect(
        frame: Image.Image,
        progress: float,
        explosion_frames: list[Image.Image] | None = None,
) -> Image.Image:
    """Composite the semi-transparent meme explosion over the source frame."""
    if progress < NUCLEAR_BOMB_START_PROGRESS or not explosion_frames:
        return frame

    overlay_progress = (
        (progress - NUCLEAR_BOMB_START_PROGRESS)
        / (1.0 - NUCLEAR_BOMB_START_PROGRESS)
    )
    overlay_index = min(
        int(overlay_progress * len(explosion_frames)),
        len(explosion_frames) - 1,
    )
    overlay = explosion_frames[overlay_index].convert("RGBA")
    scale = min(
        frame.width * NUCLEAR_BOMB_MAX_FRAME_RATIO / overlay.width,
        frame.height * NUCLEAR_BOMB_MAX_FRAME_RATIO / overlay.height,
    )
    overlay_size = (
        max(1, round(overlay.width * scale)),
        max(1, round(overlay.height * scale)),
    )
    overlay = overlay.resize(overlay_size, Image.LANCZOS)
    alpha = overlay.getchannel("A").point(
        lambda value: round(value * NUCLEAR_BOMB_OPACITY)
    )
    overlay.putalpha(alpha)

    composed = frame.convert("RGBA")
    position = (
        (frame.width - overlay.width) // 2,
        (frame.height - overlay.height) // 2,
    )
    composed.alpha_composite(overlay, position)
    return composed if frame.mode == "RGBA" else composed.convert("RGB")


def _load_nuclear_bomb_frames() -> list[Image.Image]:
    try:
        response = httpx.get(NUCLEAR_BOMB_GIF_URL, timeout=5)
        response.raise_for_status()
        explosion_gif = Image.open(BytesIO(response.content))
        frames = []
        for frame_index in range(min(explosion_gif.n_frames, 30)):
            explosion_gif.seek(frame_index)
            frames.append(explosion_gif.convert("RGBA"))
        explosion_gif.close()
        return frames
    except Exception:
        return []


def _load_explosion_frames() -> list[Image.Image]:
    """Load the ActionVFX explosion and turn its black matte into alpha."""
    try:
        if EXPLOSION_GIF_PATH.is_file():
            explosion_bytes = EXPLOSION_GIF_PATH.read_bytes()
        else:
            response = httpx.get(EXPLOSION_GIF_URL, timeout=10)
            response.raise_for_status()
            explosion_bytes = response.content
        explosion_gif = Image.open(BytesIO(explosion_bytes))
        source_frame_count = explosion_gif.n_frames
        output_frame_count = min(
            source_frame_count,
            EXPLOSION_MAX_SOURCE_FRAMES,
        )
        frame_indices = np.linspace(
            0,
            source_frame_count - 1,
            output_frame_count,
            dtype=int,
        )
        frames = []
        for frame_index in frame_indices:
            explosion_gif.seek(int(frame_index))
            frame_array = np.array(explosion_gif.convert("RGBA"))
            brightness = np.max(frame_array[:, :, :3], axis=2).astype(np.float32)
            matte_alpha = np.clip(
                (brightness - 8.0) * (255.0 / 247.0),
                0,
                255,
            ).astype(np.uint8)
            frame_array[:, :, 3] = np.minimum(
                frame_array[:, :, 3],
                matte_alpha,
            )
            frames.append(Image.fromarray(frame_array))
        explosion_gif.close()
        alpha_boxes = [
            frame.getchannel("A").getbbox()
            for frame in frames
        ]
        alpha_boxes = [box for box in alpha_boxes if box]
        if alpha_boxes:
            content_bounds = (
                min(box[0] for box in alpha_boxes),
                min(box[1] for box in alpha_boxes),
                max(box[2] for box in alpha_boxes),
                max(box[3] for box in alpha_boxes),
            )
            frames = [frame.crop(content_bounds) for frame in frames]
        return frames
    except Exception:
        return []


def _apply_explosion_effect(
        frame: Image.Image,
        progress: float,
        explosion_frames: list[Image.Image] | None = None,
) -> Image.Image:
    if not explosion_frames:
        return frame

    overlay_index = min(
        round(progress * (len(explosion_frames) - 1)),
        len(explosion_frames) - 1,
    )
    overlay = explosion_frames[overlay_index]
    scale = min(
        frame.width * EXPLOSION_MAX_FRAME_RATIO / overlay.width,
        frame.height * EXPLOSION_MAX_FRAME_RATIO / overlay.height,
    )
    overlay = overlay.resize(
        (
            max(1, round(overlay.width * scale)),
            max(1, round(overlay.height * scale)),
        ),
        Image.LANCZOS,
    )
    composed = frame.convert("RGBA")
    composed.alpha_composite(
        overlay,
        (
            (frame.width - overlay.width) // 2,
            (frame.height - overlay.height) // 2,
        ),
    )
    return composed if frame.mode == "RGBA" else composed.convert("RGB")


def _repeating_effect_progress(
        frame_index: int,
        total_frames: int,
        requested_cycles: float,
) -> float:
    """Return 0..1 progress while guaranteeing each cycle reaches its end."""
    total_frames = max(total_frames, 1)
    cycle_count = max(1, math.floor(float(requested_cycles) + 0.5))
    cycle_count = min(cycle_count, max(1, total_frames // 2))
    cycle_index = min(
        (frame_index * cycle_count) // total_frames,
        cycle_count - 1,
    )
    cycle_start = math.ceil(cycle_index * total_frames / cycle_count)
    cycle_stop = math.ceil((cycle_index + 1) * total_frames / cycle_count)
    frames_in_cycle = max(cycle_stop - cycle_start, 1)
    return (frame_index - cycle_start) / max(frames_in_cycle - 1, 1)


def _save_animation_frames(
        frames: list[Image.Image],
        durations: list[int],
        output_path: str,
        preserve_alpha: bool = False,
) -> str:
    if not frames:
        return output_path

    if preserve_alpha:
        frames = [frame.convert("RGBA") for frame in frames]
        frames[0].save(
            output_path,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            lossless=False,
            quality=82,
            method=3,
        )
        return output_path

    frames[0].save(
        output_path,
        format='GIF',
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False
    )
    return output_path


def _decode_animated_image_for_ffmpeg(media_bytes: bytes, output_path: str) -> bool:
    """Decode animated WebP/GIF with Pillow so FFmpeg receives every frame."""
    try:
        animation = Image.open(BytesIO(media_bytes))
        if not (getattr(animation, "is_animated", False) or getattr(animation, "n_frames", 1) > 1):
            animation.close()
            return False

        frames = []
        durations = []
        for frame_index in range(animation.n_frames):
            animation.seek(frame_index)
            frames.append(animation.convert("RGBA"))
            durations.append(animation.info.get("duration", 66))
        animation.close()

        frames[0].save(
            output_path,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            disposal=2,
        )
        return True
    except Exception:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


def _remove_background_from_frame(frame: Image.Image, session) -> Image.Image:
    from rembg import remove

    frame = frame.convert("RGBA")
    img_bytes = BytesIO()
    frame.save(img_bytes, format="PNG")
    output = remove(img_bytes.getvalue(), session=session)
    return Image.open(BytesIO(output)).convert("RGBA")


def _remove_background_from_animation(input_path: str, output_path: str) -> str:
    from rembg import new_session

    animation = Image.open(input_path)
    frames = []
    durations = []
    session = new_session(VIDEO_REMBG_MODEL)

    try:
        frame_index = 0
        while True:
            frame = animation.copy()
            frames.append(_remove_background_from_frame(frame, session))
            durations.append(animation.info.get('duration', 66))
            frame_index += 1
            animation.seek(frame_index)
    except EOFError:
        pass

    return _save_animation_frames(frames, durations, output_path, preserve_alpha=True)


def _remove_color_from_animation(
        input_path: str,
        output_path: str,
        preserve_alpha: bool = False,
) -> str:
    animation = Image.open(input_path)
    frames = []
    durations = []
    try:
        frame_index = 0
        while True:
            frame = animation.copy()
            frame = frame.convert("RGBA") if preserve_alpha else _convert_to_rgb(frame)
            frames.append(remove_color(frame))
            durations.append(animation.info.get("duration", 66))
            frame_index += 1
            animation.seek(frame_index)
    except EOFError:
        pass
    finally:
        animation.close()

    return _save_animation_frames(frames, durations, output_path, preserve_alpha)


def _add_caption_to_gif_frames(
        gif_path: str,
        caption_text: str,
        output_path: str,
        font_size_param: str = "l",
        preserve_alpha: bool = False,
) -> str:
    gif = Image.open(gif_path)
    frames = []
    durations = []
    try:
        frame_index = 0
        while True:
            frame = gif.copy()
            frame = frame.convert("RGBA") if preserve_alpha else _convert_to_rgb(frame)
            frame_with_caption = add_caption_to_image(frame, caption_text, font_size_param)
            frames.append(frame_with_caption)
            durations.append(gif.info.get('duration', 66))
            frame_index += 1
            gif.seek(frame_index)
    except EOFError:
        pass
    return _save_animation_frames(frames, durations, output_path, preserve_alpha)


def _add_effect_to_gif_frames(
        gif_path: str,
        output_path: str,
        effect: str,
        preserve_alpha: bool = False,
        effect_speed: float = 1.0,
) -> str:
    gif = Image.open(gif_path)
    frames = []
    durations = []
    normalized_effect = str(effect).strip().lower()
    explosion_frames = (
        _load_nuclear_bomb_frames()
        if normalized_effect in NUCLEAR_BOMB_EFFECTS
        else []
    )
    action_explosion_frames = (
        _load_explosion_frames()
        if normalized_effect == "explosion"
        else []
    )
    frame_count = 0
    try:
        while True:
            frame = gif.copy()
            frame = frame.convert("RGBA") if preserve_alpha else _convert_to_rgb(frame)
            try:
                total_frames = gif.n_frames
            except:
                total_frames = 30
            progress = frame_count / max(total_frames - 1, 1)
            if normalized_effect == "bulge":
                frame_effect = _apply_bulge_effect(frame, 0.5)
            elif normalized_effect == "pinch":
                frame_effect = _apply_pinch_effect(frame, 0.5)
            elif normalized_effect == "swirl":
                frame_effect = _apply_swirl_effect(frame, 0.5)
            elif normalized_effect == "wave":
                frame_effect = _apply_wave_effect(frame, 10)
            elif normalized_effect == "fisheye":
                frame_effect = _apply_fisheye_effect(frame, 0.5)
            elif normalized_effect == "explosion":
                explosion_progress = _repeating_effect_progress(
                    frame_count,
                    total_frames,
                    effect_speed,
                )
                frame_effect = _apply_explosion_effect(
                    frame,
                    explosion_progress,
                    action_explosion_frames,
                )
            elif normalized_effect in NUCLEAR_BOMB_EFFECTS:
                frame_effect = _apply_nuclear_bomb_effect(
                    frame,
                    progress,
                    explosion_frames,
                )
            elif normalized_effect == "breathing":
                frame_effect = _apply_breathing_effect(frame, progress)
            elif normalized_effect == "rotation":
                rotation_progress = frame_count / max(total_frames, 1)
                rotation_count = max(1, math.floor(float(effect_speed) + 0.5))
                frame_effect = _apply_rotation_effect(
                    frame,
                    rotation_progress,
                    rotation_count,
                )
            else:
                frame_effect = frame
            frames.append(frame_effect)
            durations.append(gif.info.get('duration', 66))
            frame_count += 1
            gif.seek(frame_count)
    except EOFError:
        pass
    return _save_animation_frames(frames, durations, output_path, preserve_alpha)

def _compress_gif_to_limit(input_path: str, output_path: str, max_bytes: int = 900_000) -> str:
    configs = [
        {"scale": 512, "fps": 15, "colors": 256, "duration": 10},
        {"scale": 384, "fps": 12, "colors": 128, "duration": 8},
        {"scale": 320, "fps": 10, "colors": 128, "duration": 7},
        {"scale": 256, "fps": 10, "colors": 64,  "duration": 6},
        {"scale": 192, "fps": 8,  "colors": 32,  "duration": 5},
        {"scale": 160, "fps": 6,  "colors": 32,  "duration": 4},
    ]

    for cfg in configs:
        tmp_out = output_path + ".tmp.gif"
        try:
            subprocess.run([
                'ffmpeg',
                '-i', input_path,
                '-vf',
                f'fps={cfg["fps"]},'
                f'scale={cfg["scale"]}:{cfg["scale"]}:force_original_aspect_ratio=decrease,'
                f'pad={cfg["scale"]}:{cfg["scale"]}:(ow-iw)/2:(oh-ih)/2:color=white@0,'
                f'split[s0][s1];'
                f'[s0]palettegen=max_colors={cfg["colors"]}[p];'
                f'[s1][p]paletteuse=dither=bayer:bayer_scale=5',
                '-t', str(cfg["duration"]),
                '-loop', '0',
                tmp_out,
                '-y'
            ], check=True, capture_output=True)

            size = os.path.getsize(tmp_out)
            if size <= max_bytes:
                os.rename(tmp_out, output_path)
                return output_path
            else:
                os.remove(tmp_out)
        except Exception:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            continue

    cfg = configs[-1]
    subprocess.run([
        'ffmpeg',
        '-i', input_path,
        '-vf',
        f'fps={cfg["fps"]},'
        f'scale={cfg["scale"]}:{cfg["scale"]}:force_original_aspect_ratio=decrease,'
        f'pad={cfg["scale"]}:{cfg["scale"]}:(ow-iw)/2:(oh-ih)/2:color=white@0,'
        f'split[s0][s1];'
        f'[s0]palettegen=max_colors={cfg["colors"]}[p];'
        f'[s1][p]paletteuse=dither=bayer:bayer_scale=5',
        '-t', str(cfg["duration"]),
        '-loop', '0',
        output_path,
        '-y'
    ], check=True, capture_output=True)

    return output_path


def _compress_webp_sticker(
        input_path: str,
        output_path: str,
        max_bytes: int = 490_000,
        fill: bool = False,
        max_fps: int | None = None,
) -> str:
    configs = [
        {"scale": 512, "fps": 30, "quality": 85, "duration": 7},
        {"scale": 512, "fps": 24, "quality": 75, "duration": 7},
        {"scale": 512, "fps": 20, "quality": 65, "duration": 7},
        {"scale": 512, "fps": 15, "quality": 55, "duration": 7},
        {"scale": 384, "fps": 15, "quality": 60, "duration": 7},
        {"scale": 256, "fps": 15, "quality": 60, "duration": 7},
        {"scale": 224, "fps": 12, "quality": 52, "duration": 7},
        {"scale": 192, "fps": 10, "quality": 48, "duration": 7},
        {"scale": 160, "fps": 8, "quality": 42, "duration": 6},
        {"scale": 128, "fps": 8, "quality": 38, "duration": 5},
    ]
    if max_fps is not None:
        configs = [config for config in configs if config["fps"] <= max_fps]

    for cfg in configs:
        tmp_out = output_path + ".tmp.webp"
        try:
            subprocess.run([
                'ffmpeg',
                '-i', input_path,
                '-vf',
                f'fps={cfg["fps"]},'
                f'{_square_video_filter(cfg["scale"], fill)}',
                '-vcodec', 'libwebp',
                '-lossless', '0',
                '-compression_level', '6',
                '-quality', str(cfg["quality"]),
                '-loop', '0',
                '-preset', 'picture',
                '-an',
                '-t', str(cfg["duration"]),
                tmp_out, '-y'
            ], check=True, capture_output=True)

            size = os.path.getsize(tmp_out)
            if size <= max_bytes:
                os.rename(tmp_out, output_path)
                return output_path
            else:
                os.remove(tmp_out)
        except Exception:
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
            continue

    cfg = configs[-1]
    subprocess.run([
        'ffmpeg', '-i', input_path,
        '-vf',
        f'fps={cfg["fps"]},'
        f'{_square_video_filter(cfg["scale"], fill)}',
        '-vcodec', 'libwebp',
        '-lossless', '0',
        '-compression_level', '6',
        '-quality', str(cfg["quality"]),
        '-loop', '0',
        '-preset', 'picture',
        '-an',
        '-t', str(cfg["duration"]),
        output_path, '-y'
    ], check=True, capture_output=True)

    return output_path


def _compress_alpha_webp_sticker(
        input_path: str,
        output_path: str,
        max_bytes: int = 490_000,
        minimum_stride: int = 1,
) -> str:
    """Compress an alpha animation without routing it through a GIF/FFmpeg."""
    configs = [
        {"scale": 512, "quality": 78, "stride": 1},
        {"scale": 384, "quality": 70, "stride": 1},
        {"scale": 320, "quality": 62, "stride": 1},
        {"scale": 256, "quality": 55, "stride": 1},
        {"scale": 256, "quality": 48, "stride": 2},
        {"scale": 192, "quality": 42, "stride": 2},
        {"scale": 160, "quality": 36, "stride": 3},
    ]

    for config_index, config in enumerate(configs):
        animation = Image.open(input_path)
        frames = []
        durations = []
        frame_stride = max(config["stride"], minimum_stride)
        try:
            for frame_index in range(animation.n_frames):
                if frame_index % frame_stride:
                    continue
                animation.seek(frame_index)
                frame = animation.convert("RGBA")
                if frame.size != (config["scale"], config["scale"]):
                    frame = frame.resize(
                        (config["scale"], config["scale"]),
                        Image.LANCZOS,
                    )
                frames.append(frame)
                durations.append(
                    max(
                        20,
                        int(animation.info.get("duration", 66))
                        * frame_stride,
                    )
                )
        finally:
            animation.close()

        if not frames:
            continue

        temp_output = output_path + ".tmp.webp"
        frames[0].save(
            temp_output,
            format="WEBP",
            save_all=True,
            append_images=frames[1:],
            duration=durations,
            loop=0,
            lossless=False,
            quality=config["quality"],
            method=3,
        )
        if (
                os.path.getsize(temp_output) <= max_bytes
                or config_index == len(configs) - 1
        ):
            os.replace(temp_output, output_path)
            return output_path
        os.remove(temp_output)

    return output_path


def _build_animated_sticker_webp(
        media_bytes: bytes,
        caption_text: str = None,
        effect: str = None,
        fill: bool = False,
        font_size_param: str = "l",
        remove_background: bool = False,
        speed: float = 1.0,
        cut_spec=None,
        blur: int = 0,
        no_color: bool = False,
) -> tuple[str, list[str]]:
    with tempfile.NamedTemporaryFile(suffix='.media', delete=False) as f:
        f.write(media_bytes)
        webp_path = f.name

    gif_path = tempfile.mktemp(suffix='.gif')
    output_webp_path = tempfile.mktemp(suffix='.webp')
    temp_paths = [webp_path, gif_path, output_webp_path]

    try:
        decoded_animation_path = tempfile.mktemp(suffix='.gif')
        if _decode_animated_image_for_ffmpeg(media_bytes, decoded_animation_path):
            temp_paths.append(decoded_animation_path)
            input_path = decoded_animation_path
        else:
            input_path = webp_path

        static_source = False
        try:
            with Image.open(BytesIO(media_bytes)) as source_image:
                static_source = not (
                    getattr(source_image, "is_animated", False)
                    or getattr(source_image, "n_frames", 1) > 1
                )
        except Exception:
            pass

        speed = max(float(speed), 0.1)
        normalized_effect = str(effect or "").strip().lower()
        source_fps = (
            VIDEO_REMBG_FPS
            if remove_background
            else (
                STATIC_EXPLOSION_FPS
                if static_source and normalized_effect == "explosion"
                else STATIC_EFFECT_FPS if static_source else 30
            )
        )
        source_scale = VIDEO_REMBG_SCALE if remove_background else 512
        source_duration = (
            VIDEO_REMBG_DURATION
            if remove_background
            else STATIC_EFFECT_DURATION if static_source else 6
        )
        cut_range = _parse_cut_range(cut_spec)
        cut_args = []
        if cut_range:
            cut_start, cut_duration = cut_range
            cut_args = ["-ss", f"{cut_start:.3f}"]
            source_duration = cut_duration
        timeline_speed = (
            1.0
            if normalized_effect in {"rotation", "explosion"}
            else speed
        )
        speed_filter = (
            f"setpts=PTS/{timeline_speed},"
            if timeline_speed != 1.0
            else ""
        )
        blur_level = max(0, min(100, int(blur or 0)))
        blur_filter = f"gblur=sigma={(blur_level / 100.0) * 30.0:.2f}," if blur_level else ""
        loop_args = (
            ["-stream_loop", "-1", "-t", str(source_duration)]
            if static_source
            else []
        )

        subprocess.run([
            'ffmpeg',
            *cut_args,
            *loop_args,
            '-i', input_path,
            '-vf',
            f'fps={source_fps},'
            f'{speed_filter}'
            f'{blur_filter}'
            f'{_square_video_filter(source_scale, fill)},'
            'split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=sierra2_4a',
            '-t', str(source_duration),
            '-loop', '0',
            gif_path, '-y'
        ], check=True, capture_output=True)

        working_gif = gif_path
        effect_preserves_alpha = (
            remove_background
            or str(effect or "").strip().lower() == "rotation"
        )

        # Keep background removal as the first transformation. Effects and
        # captions must operate on the already transparent frames.
        if remove_background:
            no_bg = tempfile.mktemp(suffix='.webp')
            temp_paths.append(no_bg)
            working_gif = _remove_background_from_animation(working_gif, no_bg)

        if caption_text:
            captioned = tempfile.mktemp(
                suffix='.webp' if effect_preserves_alpha else '.gif'
            )
            temp_paths.append(captioned)
            working_gif = _add_caption_to_gif_frames(
                working_gif,
                caption_text,
                captioned,
                font_size_param,
                preserve_alpha=effect_preserves_alpha,
            )

        if effect:
            effected = tempfile.mktemp(
                suffix='.webp' if effect_preserves_alpha else '.gif'
            )
            temp_paths.append(effected)
            working_gif = _add_effect_to_gif_frames(
                working_gif,
                effected,
                effect,
                preserve_alpha=effect_preserves_alpha,
                effect_speed=speed,
            )

        if no_color:
            colorless = tempfile.mktemp(
                suffix='.webp' if effect_preserves_alpha else '.gif'
            )
            temp_paths.append(colorless)
            working_gif = _remove_color_from_animation(
                working_gif,
                colorless,
                preserve_alpha=effect_preserves_alpha,
            )

        # Keep alpha animations in WebP throughout the pipeline. Converting
        # them to GIF here can make FFmpeg reject the final encode or collapse
        # the result to a single frame.
        max_output_bytes = (
            STATIC_STICKER_MAX_BYTES
            if static_source
            else VIDEO_STICKER_MAX_BYTES
        )
        if working_gif.lower().endswith('.webp'):
            _compress_alpha_webp_sticker(
                working_gif,
                output_webp_path,
                max_bytes=max_output_bytes,
                minimum_stride=1 if static_source else 2,
            )
        else:
            _compress_webp_sticker(
                working_gif,
                output_webp_path,
                max_bytes=max_output_bytes,
                fill=fill,
                max_fps=None if static_source else 20,
            )
        return output_webp_path, temp_paths

    except Exception:
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)
        raise


async def animated_sticker_from_bytes(
        media_bytes: bytes,
        caption_text: str = None,
        effect: str = None,
        fill: bool = False,
        font_size_param: str = "l",
        remove_background: bool = False,
        speed: float = 1.0,
        cut_spec=None,
        blur: int = 0,
        no_color: bool = False,
) -> str:
    output_webp_path, temp_paths = await asyncio.to_thread(
        _build_animated_sticker_webp,
        media_bytes,
        caption_text,
        effect,
        fill,
        font_size_param,
        remove_background,
        speed,
        cut_spec,
        blur,
        no_color,
    )
    try:
        gif_url = await _upload_to_tmpfile(output_webp_path)
        return gif_url

    finally:
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)


async def animated_sticker(
        db_message: Message,
        effect: str = None,
        fill: bool = False,
        font_size_param: str = "l",
        caption_text: str = None,
        remove_background: bool = False,
        speed: float = 1.0,
        cut_spec=None,
        blur: int = 0,
        no_color: bool = False,
) -> str:
    if caption_text is None:
        caption_text = clean_text(db_message.content) if db_message.content else None
    media_data = await download_media(db_message.message_id)
    media_bytes = base64.b64decode(media_data[0])
    return await animated_sticker_from_bytes(
        media_bytes,
        caption_text,
        effect,
        fill,
        font_size_param,
        remove_background=remove_background,
        speed=speed,
        cut_spec=cut_spec,
        blur=blur,
        no_color=no_color,
    )
