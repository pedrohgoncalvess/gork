import textwrap

from PIL import ImageFont, ImageDraw, Image

from utils import project_root


def add_caption_to_image(img: Image.Image, caption_text: str = "") -> Image.Image:
    """
    Add meme-style text to image with automatic top/bottom split.

    Args:
        img: PIL Image
        caption_text: Caption text (use '|' to split top/bottom, or auto-split by length)
    """
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

    font_size = int(height / 8)
    font_size = max(30, min(font_size, 100))

    font = ImageFont.truetype(f"{project_root}/data/fonts/arial-bold.ttf", font_size)

    if top_text:
        draw_meme_text(draw, top_text.upper(), font, width, height, position="top")

    if bottom_text:
        draw_meme_text(draw, bottom_text.upper(), font, width, height, position="bottom")

    return img


def draw_meme_text(draw, text: str, font, width: int, height: int, position: str = "top"):
    max_chars = max(12, width // (font.size // 2))
    lines = textwrap.wrap(text, width=max_chars)

    if len(lines) == 1 and len(text) > max_chars:
        words = text.split()
        lines = []
        current_line = []

        for word in words:
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] < width - 40:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word]

        if current_line:
            lines.append(' '.join(current_line))

    line_height = int(font.size * 1.2)

    if position == "top":
        y = 10
    else:
        total_height = len(lines) * line_height
        y = height - total_height - 10

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2

        outline_width = max(2, font.size // 15)

        for offset_x in range(-outline_width, outline_width + 1):
            for offset_y in range(-outline_width, outline_width + 1):
                if offset_x != 0 or offset_y != 0:
                    draw.text(
                        (x + offset_x, y + offset_y),
                        line,
                        font=font,
                        fill=(0, 0, 0, 255)
                    )

        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))

        y += line_height