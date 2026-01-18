import base64
import subprocess
import tempfile
import os
import math
from io import BytesIO

import numpy as np
import httpx
from PIL import Image, ImageFont

from external.evolution import download_media
from functions.sticker import add_caption_to_image


async def upload_to_tmpfile(gif_path: str) -> str:
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


def calculate_font_size(text: str, max_height: int) -> int:
    base_size = max(20, int(max_height * 0.08))

    text_length = len(text)
    if text_length > 100:
        return max(20, int(base_size * 0.6))
    elif text_length > 50:
        return max(25, int(base_size * 0.75))
    elif text_length > 30:
        return max(30, int(base_size * 0.85))
    else:
        return base_size


def split_text_smart(text: str, max_chars_per_line: int = 25) -> tuple[str, str]:
    if "|" in text:
        parts = text.split("|", 1)
        return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""

    words = text.split()

    if len(text) <= max_chars_per_line:
        return text, ""

    mid_point = len(words) // 2

    top_text = " ".join(words[:mid_point])
    bottom_text = " ".join(words[mid_point:])

    if len(top_text) > max_chars_per_line * 2:
        top_words = []
        current_length = 0
        for word in words:
            if current_length + len(word) + 1 > max_chars_per_line * 2:
                break
            top_words.append(word)
            current_length += len(word) + 1

        top_text = " ".join(top_words)
        bottom_text = " ".join(words[len(top_words):])

    return top_text, bottom_text


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = font.getbbox(test_line)
        width = bbox[2] - bbox[0]

        if width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines if lines else [text]


def add_caption_to_gif_frames(gif_path: str, caption_text: str, output_path: str) -> str:
    gif = Image.open(gif_path)
    frames = []
    durations = []

    try:
        frame_index = 0
        while True:
            frame = gif.copy()
            if frame.mode != 'RGB':
                if frame.mode == 'P':
                    frame = frame.convert('RGBA').convert('RGB')
                else:
                    frame = frame.convert('RGB')

            frame_with_caption = add_caption_to_image(frame, caption_text)
            frames.append(frame_with_caption)

            durations.append(gif.info.get('duration', 66))

            frame_index += 1
            gif.seek(frame_index)
    except EOFError:
        pass

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


def apply_bulge_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]

    center_x, center_y = width // 2, height // 2

    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    new_img = np.zeros_like(img_array)

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
                    else:
                        new_img[y, x] = img_array[y, x]
                else:
                    new_img[y, x] = img_array[y, x]
            else:
                new_img[y, x] = img_array[y, x]

    return Image.fromarray(new_img)


def apply_pinch_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]

    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    new_img = np.zeros_like(img_array)

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
                else:
                    new_img[y, x] = img_array[y, x]
            else:
                new_img[y, x] = img_array[y, x]

    return Image.fromarray(new_img)


def apply_swirl_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]

    center_x, center_y = width // 2, height // 2
    max_radius = math.sqrt(center_x ** 2 + center_y ** 2)

    new_img = np.zeros_like(img_array)

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
                else:
                    new_img[y, x] = img_array[y, x]
            else:
                new_img[y, x] = img_array[y, x]

    return Image.fromarray(new_img)


def apply_wave_effect(frame: Image.Image, intensity: float = 10) -> Image.Image:
    img_array = np.array(frame)
    height, width = img_array.shape[:2]

    new_img = np.zeros_like(img_array)

    for y in range(height):
        offset = int(intensity * math.sin(y * 0.1))
        for x in range(width):
            src_x = (x + offset) % width
            new_img[y, x] = img_array[y, src_x]

    return Image.fromarray(new_img)


def apply_fisheye_effect(frame: Image.Image, intensity: float = 0.5) -> Image.Image:
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


def apply_breathing_effect(frame: Image.Image, progress: float) -> Image.Image:
    intensity = math.sin(progress * math.pi * 2) * 0.3

    if intensity > 0:
        return apply_bulge_effect(frame, intensity)
    else:
        return apply_pinch_effect(frame, abs(intensity))


def apply_rotation_effect(frame: Image.Image, progress: float) -> Image.Image:
    angle = progress * 360
    return frame.rotate(-angle, resample=Image.BICUBIC, expand=False, fillcolor=(0, 0, 0))


def apply_explosion_effect(frame: Image.Image, progress: float, explosion_frames: list = None,
                           explosion_index: int = 0) -> Image.Image:
    if progress >= 0.8 and explosion_frames and isinstance(explosion_frames, list) and len(explosion_frames) > 0:
        return explosion_frames[min(explosion_index, len(explosion_frames) - 1)]

    return frame


def add_effect_to_gif_frames(gif_path: str, output_path: str, effect: str) -> str:
    gif = Image.open(gif_path)
    frames = []
    durations = []

    explosion_frames = []
    if effect == "explosion":
        try:
            explosion_url = "https://media.giphy.com/media/HhTXt43pk1I1W/giphy.gif"
            import requests
            from io import BytesIO

            response = requests.get(explosion_url, timeout=5)
            explosion_gif = Image.open(BytesIO(response.content))

            explosion_frame_count = 0
            try:
                while explosion_frame_count < 30:  # ~1.5 segundos a 15fps
                    explosion_gif.seek(explosion_frame_count)
                    exp_frame = explosion_gif.copy()

                    if exp_frame.mode != 'RGB':
                        if exp_frame.mode == 'P':
                            exp_frame = exp_frame.convert('RGBA').convert('RGB')
                        else:
                            exp_frame = exp_frame.convert('RGB')

                    exp_frame = exp_frame.resize((gif.width, gif.height), Image.LANCZOS)
                    explosion_frames.append(exp_frame)
                    explosion_frame_count += 1
            except EOFError:
                pass
        except:
            pass

    frame_count = 0
    explosion_frame_index = 0
    try:
        while True:
            frame = gif.copy()
            if frame.mode != 'RGB':
                if frame.mode == 'P':
                    frame = frame.convert('RGBA').convert('RGB')
                else:
                    frame = frame.convert('RGB')

            try:
                total_frames = gif.n_frames
            except:
                total_frames = 30

            progress = frame_count / max(total_frames - 1, 1)

            if effect == "bulge":
                frame_effect = apply_bulge_effect(frame, 0.5)
            elif effect == "pinch":
                frame_effect = apply_pinch_effect(frame, 0.5)
            elif effect == "swirl":
                frame_effect = apply_swirl_effect(frame, 0.5)
            elif effect == "wave":
                frame_effect = apply_wave_effect(frame, 10)
            elif effect == "fisheye":
                frame_effect = apply_fisheye_effect(frame, 0.5)
            elif effect == "explosion":
                frame_effect = apply_explosion_effect(frame, progress, explosion_frames, explosion_frame_index)
                if progress >= 0.7 and explosion_frames:
                    explosion_frame_index += 1
            elif effect == "breathing":
                frame_effect = apply_breathing_effect(frame, progress)
            elif effect == "rotation":
                frame_effect = apply_rotation_effect(frame, progress)
            else:
                frame_effect = frame

            frames.append(frame_effect)
            durations.append(gif.info.get('duration', 66))

            frame_count += 1
            gif.seek(frame_count)
    except EOFError:
        pass

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


async def animated(message_id: str, caption_text: str = None, effect: str = None) -> str:
    media_data = await download_media(message_id, True)
    media_base64 = media_data[0]
    media_bytes = base64.b64decode(media_base64)

    with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as temp_input:
        temp_input.write(media_bytes)
        webp_path = temp_input.name

    gif_path = tempfile.mktemp(suffix='.gif')
    gif_with_caption_path = tempfile.mktemp(suffix='.gif')
    gif_with_effect_path = tempfile.mktemp(suffix='.gif')

    try:
        is_webp_animated = False
        try:
            test_img = Image.open(webp_path)
            is_webp_animated = test_img.format == 'WEBP' and hasattr(test_img, 'n_frames') and test_img.n_frames > 1
            test_img.close()
        except:
            pass

        if is_webp_animated:
            webp = Image.open(webp_path)
            frames = []
            durations = []

            original_width = webp.width
            original_height = webp.height

            try:
                frame_index = 0
                while frame_index < min(webp.n_frames, 105):
                    webp.seek(frame_index)
                    frame = webp.copy()

                    if frame.mode != 'RGB':
                        if frame.mode == 'P':
                            frame = frame.convert('RGBA').convert('RGB')
                        elif frame.mode == 'RGBA':
                            background = Image.new('RGB', frame.size, (255, 255, 255))
                            background.paste(frame, mask=frame.split()[3])
                            frame = background
                        else:
                            frame = frame.convert('RGB')

                    frames.append(frame)

                    duration = webp.info.get('duration', 66)
                    durations.append(duration)

                    frame_index += 1
            except EOFError:
                pass

            webp.close()

            if frames:
                frames[0].save(
                    gif_path,
                    format='GIF',
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=0,
                    optimize=False
                )
            else:
                raise Exception("Nenhum frame foi extraído do WebP")
        else:
            # Para vídeos MP4, também mantém proporção melhor
            subprocess.run([
                'ffmpeg',
                '-i', webp_path,
                '-vf',
                'fps=15,'
                'scale=512:512:force_original_aspect_ratio=decrease,'  # decrease ao invés de increase
                'pad=512:512:(ow-iw)/2:(oh-ih)/2:black,'  # adiciona padding preto se necessário
                'split[s0][s1];'
                '[s0]palettegen=max_colors=256[p];'
                '[s1][p]paletteuse=dither=bayer:bayer_scale=5',
                '-t', '7',
                '-loop', '0',
                gif_path,
                '-y'
            ], check=True, capture_output=True)

        final_gif_path = gif_path

        if caption_text:
            final_gif_path = add_caption_to_gif_frames(gif_path, caption_text, gif_with_caption_path)

        if effect:
            input_for_effect = final_gif_path
            final_gif_path = add_effect_to_gif_frames(input_for_effect, gif_with_effect_path, effect)

        gif_url = await upload_to_tmpfile(final_gif_path)

        return gif_url

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        raise Exception(f"Erro ao processar mídia: {error_msg}")
    except Exception as e:
        raise Exception(f"Erro ao processar mídia: {str(e)}")

    finally:
        if os.path.exists(webp_path):
            os.remove(webp_path)
        if os.path.exists(gif_path):
            os.remove(gif_path)
        if os.path.exists(gif_with_caption_path):
            os.remove(gif_with_caption_path)
        if os.path.exists(gif_with_effect_path):
            os.remove(gif_with_effect_path)