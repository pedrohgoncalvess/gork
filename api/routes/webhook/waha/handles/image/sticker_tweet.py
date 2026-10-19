"""Render a compact tweet card inside a transparent 512px sticker."""

import base64
from io import BytesIO

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from api.routes.webhook.waha.handles.image.sticker_caption import (
    _iter_text_tokens,
    _load_emoji_font,
    _load_text_font,
)
from api.routes.webhook.waha.handles.social import TwitterCardDownloadResult


def _runs(text, font):
    """Keep original case and render emoji with the bundled emoji font."""
    for token, is_emoji in _iter_text_tokens(text):
        yield token, (_load_emoji_font(font.size) or font) if is_emoji else font


def _width(draw, text, font):
    return sum(draw.textlength(token, font=run_font) for token, run_font in _runs(text, font))


def _draw_line(draw, text, xy, font, fill):
    x, y = xy
    for token, run_font in _runs(text, font):
        draw.text((x, y), token, font=run_font, fill=fill, embedded_color=True)
        x += draw.textlength(token, font=run_font)


def _ellipsize(draw, text, font, width):
    text = text[:1000] + ("…" if len(text) > 1000 else "")
    if _width(draw, text, font) <= width:
        return text
    while text and _width(draw, text + "…", font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(draw, text, font, width):
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = line + word
            if line and _width(draw, candidate, font) > width:
                lines.append(line)
                line = ""
            if _width(draw, word, font) <= width:
                line += word
            else:
                # Split long URLs/words as well, so no text escapes the card.
                for char in word:
                    candidate = line + char
                    if line and _width(draw, candidate, font) > width:
                        lines.append(line.rstrip())
                        line = ""
                    line += char
            line += " "
        lines.append(line.rstrip())
    return lines


def _fit_text(draw, text, width, height):
    text = (text or "").strip()
    clipped = len(text) > 4000
    text = text[:4000]
    for size in range(26, 19, -2):
        font = _load_text_font(size)
        line_height = size + 7
        lines = _wrap(draw, text, font, width) if text else []
        if len(lines) * line_height <= height:
            break
    count = height // line_height
    if len(lines) > count or clipped:
        lines = lines[:count]
        if lines:
            lines[-1] = _ellipsize(draw, lines[-1] + "…", font, width)
    return font, line_height, lines


def _open_optional(payload):
    if not payload:
        return None
    try:
        with Image.open(BytesIO(payload)) as image:
            return ImageOps.exif_transpose(image).convert("RGBA")
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def render_tweet_sticker(tweet: TwitterCardDownloadResult) -> str:
    canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    photo = _open_optional(tweet.photo_bytes)
    font, line_height, lines = _fit_text(draw, tweet.text, 440, 208 if photo else 340)
    text_height = len(lines) * line_height
    photo_height = min(220, 384 - text_height) if photo else 0
    card_height = 88 + text_height + (photo_height + 14 if photo else 0) + 24
    top = (512 - card_height) // 2
    draw.rounded_rectangle((12, top, 500, top + card_height), radius=24,
                           fill="white", outline=(225, 230, 234), width=1)
    avatar_box = (32, top + 20, 84, top + 72)
    draw.ellipse(avatar_box, fill=(225, 235, 242))
    avatar = _open_optional(tweet.avatar_bytes)
    if avatar:
        avatar = ImageOps.fit(avatar, (52, 52), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (52, 52))
        ImageDraw.Draw(mask).ellipse((0, 0, 51, 51), fill=255)
        canvas.paste(avatar, (32, top + 20), mask)
    else:
        _draw_line(draw, (tweet.author_name or "?")[0], (49, top + 29),
                   _load_text_font(24), (70, 100, 120))
    name_font, handle_font = _load_text_font(23), _load_text_font(19)
    name = _ellipsize(draw, tweet.author_name or tweet.author_handle, name_font, 340)
    handle = _ellipsize(draw, "@" + tweet.author_handle.lstrip("@"), handle_font, 340)
    _draw_line(draw, name, (98, top + 18), name_font, (15, 20, 25))
    _draw_line(draw, handle, (98, top + 47), handle_font, (83, 100, 113))
    y = top + 88
    for line in lines:
        _draw_line(draw, line, (36, y), font, (15, 20, 25))
        y += line_height
    if photo:
        y += 14
        # Contain preserves the whole photo, including tall or wide originals.
        tile = Image.new("RGBA", (440, photo_height), (239, 243, 246))
        fitted = ImageOps.contain(photo, tile.size, method=Image.Resampling.LANCZOS)
        tile.alpha_composite(fitted, ((440 - fitted.width) // 2, (photo_height - fitted.height) // 2))
        mask = Image.new("L", tile.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 439, photo_height - 1), radius=16, fill=255)
        canvas.paste(tile, (36, y), mask)
    # Keep the static sticker below 100 KiB, including detailed photos.
    for quality in (95, 85, 75, 60, 45, 30, 15, 5):
        buffer = BytesIO()
        canvas.save(buffer, format="WEBP", quality=quality, method=6)
        if buffer.tell() <= 100 * 1024:
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    raise ValueError("Não foi possível comprimir a figurinha do tweet.")
