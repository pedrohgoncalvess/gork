from functools import lru_cache
from io import BytesIO
from pathlib import Path
import tempfile
import unicodedata
from urllib.error import URLError
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

from utils import project_root


TEXT_FONT_PATH = f"{project_root}/utils/fonts/arial-bold.ttf"
EMOJI_FONT_PATH = f"{project_root}/utils/fonts/noto-emoji.ttf"
EMOJI_FONT_CANDIDATES = (
    f"{project_root}/utils/fonts/NotoColorEmoji.ttf",
    f"{project_root}/utils/fonts/noto-color-emoji.ttf",
    f"{project_root}/utils/fonts/seguiemj.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto-color-emoji/NotoColorEmoji.ttf",
    EMOJI_FONT_PATH,
)
TWEMOJI_BASE_URL = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72"
TWEMOJI_ASSET_DIR = Path(project_root) / "utils" / "emoji" / "twemoji"
TWEMOJI_CACHE_DIR = Path(project_root) / ".cache" / "twemoji"

_VARIATION_SELECTORS = {"\ufe0e", "\ufe0f"}
_ZERO_WIDTH_JOINER = "\u200d"


def add_caption_to_image(img: Image.Image, caption_text: str = "") -> Image.Image:
    if not caption_text:
        return img

    top_text = ""
    bottom_text = ""

    if '|' in caption_text:
        parts = caption_text.split('|', 1)
        top_text = parts[0].strip()
        bottom_text = parts[1].strip()
    else:
        words = caption_text.strip().split()
        total_words = len(words)
        if total_words <= 3:
            bottom_text = caption_text
        elif total_words <= 6:
            mid = total_words // 2
            top_text = ' '.join(words[:mid])
            bottom_text = ' '.join(words[mid:])
        else:
            mid = total_words // 2
            top_text = ' '.join(words[:mid])
            bottom_text = ' '.join(words[mid:])

    img = img.copy()
    width, height = img.size
    draw = ImageDraw.Draw(img)

    if top_text:
        _draw_meme_text(img, draw, top_text, width, height, position="top")

    if bottom_text:
        _draw_meme_text(img, draw, bottom_text, width, height, position="bottom")

    return img


def _draw_meme_text(img: Image.Image, draw, text: str, width: int, height: int, position: str = "top"):
    margin_x = int(width * 0.05)
    usable_width = width - (2 * margin_x)

    font_size = int(height / 8)
    font_size = max(30, min(font_size, 120))

    best_font = None
    best_lines = []

    for size in range(font_size, 20, -5):
        font = _load_text_font(size)

        lines = _wrap_text_to_width(draw, text, font, usable_width)

        line_height = int(size * 1.2)
        total_text_height = len(lines) * line_height

        max_text_height = (height // 2) - 40

        if total_text_height <= max_text_height:
            best_font = font
            best_lines = lines
            break
    if best_font is None:
        best_font = _load_text_font(25)
        best_lines = _wrap_text_to_width(draw, text, best_font, usable_width)

    line_height = int(best_font.size * 1.2)
    total_height = len(best_lines) * line_height

    if position == "top":
        y = 20
    else:
        y = height - total_height - 20

    outline_width = max(2, best_font.size // 15)

    for line in best_lines:
        text_width = _measure_tokens(draw, line, best_font)
        x = (width - text_width) // 2
        _draw_token_line(img, draw, line, x, y, best_font, outline_width)
        y += line_height


def _wrap_text_to_width(draw, text: str, font, max_width: int) -> list:
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        text_width = _measure_tokens(draw, test_line, font)

        if text_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)

    if current_line:
        lines.append(' '.join(current_line))

    return lines if lines else [text]


@lru_cache(maxsize=32)
def _load_text_font(size: int):
    try:
        return ImageFont.truetype(TEXT_FONT_PATH, size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=32)
def _load_emoji_font(size: int):
    for font_path in EMOJI_FONT_CANDIDATES:
        if not Path(font_path).exists():
            continue
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            continue
    return None


def _measure_tokens(draw, text: str, font) -> int:
    width = 0
    for token, is_emoji in _iter_text_tokens(text):
        if is_emoji:
            width += _emoji_token_width(token, font.size)
            continue

        text_token = token.upper()
        bbox = draw.textbbox((0, 0), text_token, font=font)
        width += bbox[2] - bbox[0]
    return width


def _draw_token_line(
        img: Image.Image,
        draw,
        line: str,
        x: int,
        y: int,
        font,
        outline_width: int,
) -> None:
    cursor_x = x

    for token, is_emoji in _iter_text_tokens(line):
        if is_emoji:
            emoji_img = _render_emoji_token(token, font.size, outline_width)
            token_y = y - max(0, (emoji_img.height - font.size) // 2)
            img.alpha_composite(emoji_img, (int(cursor_x), int(token_y)))
            cursor_x += emoji_img.width - (outline_width * 2)
            continue

        text_token = token.upper()
        for offset_x in range(-outline_width, outline_width + 1):
            for offset_y in range(-outline_width, outline_width + 1):
                if offset_x != 0 or offset_y != 0:
                    draw.text(
                        (cursor_x + offset_x, y + offset_y),
                        text_token,
                        font=font,
                        fill=(0, 0, 0, 255)
                    )

        draw.text((cursor_x, y), text_token, font=font, fill=(255, 255, 255, 255))
        bbox = draw.textbbox((0, 0), text_token, font=font)
        cursor_x += bbox[2] - bbox[0]


@lru_cache(maxsize=512)
def _render_emoji_token(token: str, size: int, outline_width: int) -> Image.Image:
    twemoji = _render_twemoji_token(token, size, outline_width)
    if twemoji is not None:
        return twemoji

    emoji_font = _load_emoji_font(size)
    if emoji_font is None:
        emoji_font = _load_text_font(size)

    token = _display_emoji_token(token)
    padding = max(outline_width * 2, size // 10)
    scratch = Image.new("RGBA", (max(size * 4, (len(token) + 2) * size), size * 3), (0, 0, 0, 0))
    scratch_draw = ImageDraw.Draw(scratch)
    scratch_draw.text(
        (padding, padding),
        token,
        font=emoji_font,
        embedded_color=True,
        fill=(255, 255, 255, 255),
    )

    bbox = scratch.getbbox()
    if bbox is None:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    glyph = scratch.crop(bbox)

    canvas = Image.new(
        "RGBA",
        (glyph.width + padding * 2, glyph.height + padding * 2),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(glyph, (padding, padding))
    return canvas


def _emoji_token_width(token: str, size: int) -> int:
    return max(size, _render_emoji_token(token, size, 0).width)


def _render_twemoji_token(token: str, size: int, outline_width: int) -> Image.Image | None:
    asset = _load_twemoji_asset(token)
    if asset is None:
        return None

    padding = max(outline_width * 2, size // 10)
    target_height = max(1, size)
    target_width = max(1, round(asset.width * (target_height / asset.height)))
    glyph = asset.resize((target_width, target_height), Image.Resampling.LANCZOS)

    canvas = Image.new(
        "RGBA",
        (glyph.width + padding * 2, glyph.height + padding * 2),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(glyph, (padding, padding))
    return canvas


@lru_cache(maxsize=512)
def _load_twemoji_asset(token: str) -> Image.Image | None:
    for filename in _twemoji_filenames(token):
        image = _read_twemoji_from_assets(filename)
        if image is not None:
            return image

        image = _read_twemoji_from_cache(filename)
        if image is not None:
            return image

        image_bytes = _download_twemoji_asset(filename)
        if image_bytes is None:
            continue

        _write_twemoji_to_cache(filename, image_bytes)
        try:
            return Image.open(BytesIO(image_bytes)).convert("RGBA")
        except OSError:
            continue

    return None


def _read_twemoji_from_assets(filename: str) -> Image.Image | None:
    path = TWEMOJI_ASSET_DIR / filename
    if not path.exists():
        return None

    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def _read_twemoji_from_cache(filename: str) -> Image.Image | None:
    path = _twemoji_cache_path(filename)
    if not path.exists():
        return None

    try:
        return Image.open(path).convert("RGBA")
    except OSError:
        return None


def _download_twemoji_asset(filename: str) -> bytes | None:
    try:
        with urlopen(f"{TWEMOJI_BASE_URL}/{filename}", timeout=2) as response:
            if response.status != 200:
                return None
            return response.read()
    except (OSError, URLError):
        return None


def _write_twemoji_to_cache(filename: str, image_bytes: bytes) -> None:
    path = _twemoji_cache_path(filename)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(image_bytes)
    except OSError:
        return


def _twemoji_cache_path(filename: str) -> Path:
    try:
        TWEMOJI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return TWEMOJI_CACHE_DIR / filename
    except OSError:
        return Path(tempfile.gettempdir()) / "gork-twemoji" / filename


def _twemoji_filenames(token: str) -> list[str]:
    codepoints = [ord(char) for char in token]
    without_text_variation = [cp for cp in codepoints if cp != 0xFE0E]
    without_emoji_variation = [cp for cp in without_text_variation if cp != 0xFE0F]

    candidates = [
        without_text_variation,
        without_emoji_variation,
        [cp for cp in without_emoji_variation if cp != 0x200D],
        [cp for cp in without_emoji_variation if not 0x1F3FB <= cp <= 0x1F3FF],
    ]

    filenames = []
    for candidate in candidates:
        if not candidate:
            continue
        filename = "-".join(f"{codepoint:x}" for codepoint in candidate) + ".png"
        if filename not in filenames:
            filenames.append(filename)

    return filenames


def _display_emoji_token(token: str) -> str:
    return ''.join(
        char for char in token
        if char != _ZERO_WIDTH_JOINER
        and char not in _VARIATION_SELECTORS
        and not _is_emoji_modifier(char)
    )


def _iter_text_tokens(text: str):
    current = []
    current_is_emoji = None
    index = 0

    while index < len(text):
        char = text[index]
        token = char
        is_emoji = _is_emoji_char(char)
        index += 1

        while index < len(text):
            next_char = text[index]
            if next_char in _VARIATION_SELECTORS or _is_emoji_modifier(next_char):
                token += next_char
                index += 1
                continue
            if next_char == _ZERO_WIDTH_JOINER and index + 1 < len(text):
                token += next_char + text[index + 1]
                index += 2
                continue
            break

        if current and (current_is_emoji != is_emoji or is_emoji):
            yield ''.join(current), current_is_emoji
            current = []

        current.append(token)
        current_is_emoji = is_emoji

    if current:
        yield ''.join(current), current_is_emoji


def _is_emoji_char(char: str) -> bool:
    codepoint = ord(char)
    if char in {"©", "®", "™", "#", "*"}:
        return True
    if 0x1F000 <= codepoint <= 0x1FAFF:
        return True
    if 0x2600 <= codepoint <= 0x27BF:
        return True
    return "EMOJI" in unicodedata.name(char, "")


def _is_emoji_modifier(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F3FB <= codepoint <= 0x1F3FF
        or char in _VARIATION_SELECTORS
        or char == "\u20e3"
    )
