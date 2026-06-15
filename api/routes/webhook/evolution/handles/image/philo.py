"""
Philosopher image composer for the !philo command.

Flow
----
1. Resolve the philosopher (random if :quote not given).
2. Open the local photo from assets/philosophys/.
3. Overlay the quoted message in the photo's "empty" area with auto-scaling font.
   - Newlines in the quote are preserved as hard line-breaks.
   - Emojis are rendered via the same Twemoji pipeline used by !sticker.
4. Append "– {name} · {period}" right below the quote (smaller, dimmer).
5. Draw a single semi-transparent scrim behind the whole block.
6. Return a JPEG base64 string ready to pass to send_image().
"""

from __future__ import annotations

import base64
import random
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from assets.philosophys.philo_data import (
    PHILOSOPHERS,
    PhilosopherData,
    get_philosopher,
)
# Re-use the Twemoji token machinery from sticker_caption (no uppercase forced here)
from api.routes.webhook.evolution.handles.image.sticker_caption import (
    _emoji_token_width,
    _iter_text_tokens,
    _render_emoji_token,
)
from utils import project_root

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_FONT_PATH = Path(project_root) / "assets" / "fonts" / "arial-bold.ttf"
_PHILOSOPHYS_DIR = Path(project_root) / "assets" / "philosophys"

_MAX_FONT_SIZE = 64
_MIN_FONT_SIZE = 14

# Attribution font is this fraction of the quote font size
_ATTR_FONT_RATIO = 0.62

# Vertical gap between last quote line and attribution
_ATTR_GAP = 8


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_philo_image(
    quote: str,
    philosopher_key: Optional[str] = None,
) -> tuple[str, PhilosopherData]:
    """
    Compose the philosopher image and return (jpeg_base64, philosopher).

    Parameters
    ----------
    quote:
        The text to overlay (quoted message content). Newlines are preserved.
    philosopher_key:
        Slug / alias from :quote= param.  None → random selection.
    """
    philo = get_philosopher(philosopher_key) or random.choice(PHILOSOPHERS)

    img = _open_philosopher_image(philo)
    img = _draw_quote_on_image(img, quote, philo)

    buffer = BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=92)
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8"), philo


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _open_philosopher_image(philo: PhilosopherData) -> Image.Image:
    path = _PHILOSOPHYS_DIR / philo.filename
    return Image.open(path).convert("RGBA")


def _draw_quote_on_image(
    img: Image.Image,
    quote: str,
    philo: PhilosopherData,
) -> Image.Image:
    """
    Draw quote + attribution inside the philosopher's text box.

    Layout:
        [pad_y]
        quote line 1
        quote line 2  …
        [_ATTR_GAP px]
        – Name · Period   (smaller, dimmer)
        [pad_y]
    """
    w, h = img.size
    x_frac, y_frac, bw_frac, bh_frac = philo.text_box

    box_x = int(x_frac * w)
    box_y = int(y_frac * h)
    box_w = int(bw_frac * w)
    box_h = int(bh_frac * h)

    pad_x = max(8, int(box_w * 0.06))
    pad_y = max(6, int(box_h * 0.06))
    usable_w = box_w - 2 * pad_x
    usable_h = box_h - 2 * pad_y

    attr_text = f"\u2013 {philo.display_name}  \u00b7  {philo.period}"

    draw = ImageDraw.Draw(img, "RGBA")

    # --- Find the largest font where quote + attribution fits vertically ---
    best_q_font = best_a_font = None
    best_q_lines: list[str] = []
    best_q_line_h = best_a_line_h = 0

    for size in range(_MAX_FONT_SIZE, _MIN_FONT_SIZE - 1, -1):
        q_font = _load_font(size)
        q_lines = _wrap_text_with_newlines(draw, quote, q_font, usable_w)
        q_line_h = int(size * 1.35)
        q_total_h = len(q_lines) * q_line_h

        attr_size = max(_MIN_FONT_SIZE, int(size * _ATTR_FONT_RATIO))
        a_font = _load_font(attr_size)
        a_line_h = int(attr_size * 1.35)

        if q_total_h + _ATTR_GAP + a_line_h <= usable_h:
            best_q_font = q_font
            best_q_lines = q_lines
            best_q_line_h = q_line_h
            best_a_font = a_font
            best_a_line_h = a_line_h
            break

    # Absolute fallback
    if best_q_font is None:
        best_q_font = _load_font(_MIN_FONT_SIZE)
        best_q_lines = _wrap_text_with_newlines(draw, quote, best_q_font, usable_w)
        best_q_line_h = int(_MIN_FONT_SIZE * 1.35)
        attr_size = max(10, int(_MIN_FONT_SIZE * _ATTR_FONT_RATIO))
        best_a_font = _load_font(attr_size)
        best_a_line_h = int(attr_size * 1.35)

    q_total_h = len(best_q_lines) * best_q_line_h
    block_h = q_total_h + _ATTR_GAP + best_a_line_h

    # --- Scrim sized to the actual content ---
    scrim_h = block_h + 2 * pad_y
    scrim = Image.new("RGBA", (box_w, scrim_h), (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    scrim_draw.rounded_rectangle(
        [0, 0, box_w - 1, scrim_h - 1],
        radius=10,
        fill=(0, 0, 0, 150),
    )
    img.alpha_composite(scrim, (box_x, box_y))

    # --- Draw quote lines (with emoji support, original case) ---
    q_outline = max(1, best_q_font.size // 20)
    cur_y = box_y + pad_y

    for line in best_q_lines:
        _draw_rich_text_line(img, draw, box_x + pad_x, cur_y, line, best_q_font, q_outline)
        cur_y += best_q_line_h

    # --- Draw attribution ---
    cur_y += _ATTR_GAP
    a_outline = max(1, best_a_font.size // 20)
    # attr has no emojis, plain draw is fine; dimmer fill
    _draw_outlined_text(draw, box_x + pad_x, cur_y, attr_text, best_a_font, a_outline,
                        fill=(210, 210, 210, 255))

    return img


# ---------------------------------------------------------------------------
# Rich text (emoji-aware) helpers
# ---------------------------------------------------------------------------

def _measure_rich_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    """Measure pixel width of a mixed text+emoji string (original case)."""
    width = 0
    for token, is_emoji in _iter_text_tokens(text):
        if is_emoji:
            width += _emoji_token_width(token, font.size)
        else:
            bbox = draw.textbbox((0, 0), token, font=font)
            width += bbox[2] - bbox[0]
    return width


def _draw_rich_text_line(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    line: str,
    font: ImageFont.FreeTypeFont,
    outline: int,
) -> None:
    """
    Draw a single line that may contain emojis (via Twemoji) and plain text.
    Preserves original case (unlike sticker_caption which forces uppercase).
    """
    cursor_x = x

    for token, is_emoji in _iter_text_tokens(line):
        if is_emoji:
            emoji_img = _render_emoji_token(token, font.size, outline)
            token_y = y - max(0, (emoji_img.height - font.size) // 2)
            img.alpha_composite(emoji_img, (int(cursor_x), int(token_y)))
            cursor_x += emoji_img.width - (outline * 2)
        else:
            # Outline
            for dx in range(-outline, outline + 1):
                for dy in range(-outline, outline + 1):
                    if dx != 0 or dy != 0:
                        draw.text((cursor_x + dx, y + dy), token, font=font, fill=(0, 0, 0, 230))
            draw.text((cursor_x, y), token, font=font, fill=(255, 255, 255, 255))
            bbox = draw.textbbox((0, 0), token, font=font)
            cursor_x += bbox[2] - bbox[0]


# ---------------------------------------------------------------------------
# Text wrapping (newline-aware)
# ---------------------------------------------------------------------------

def _wrap_text_with_newlines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """
    Wrap text respecting hard newlines.

    Each \\n in the source creates a hard line break; within each paragraph
    words are wrapped to fit max_width.
    """
    all_lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            all_lines.append("")          # preserve blank lines
        else:
            all_lines.extend(_wrap_paragraph(draw, paragraph, font, max_width))
    return all_lines or [""]


def _wrap_paragraph(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    """Word-wrap a single paragraph using emoji-aware width measurement."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        if _measure_rich_text(draw, candidate, font) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]

    if current:
        lines.append(" ".join(current))

    return lines or [text]


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_outlined_text(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    outline: int,
    fill: tuple = (255, 255, 255, 255),
) -> None:
    """Plain (no-emoji) outlined text draw."""
    for dx in range(-outline, outline + 1):
        for dy in range(-outline, outline + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 230))
    draw.text((x, y), text, font=font, fill=fill)


@lru_cache(maxsize=64)
def _load_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(_FONT_PATH), size)
    except OSError:
        return ImageFont.load_default()
