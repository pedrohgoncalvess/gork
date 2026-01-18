from PIL import ImageFont, ImageDraw, Image
from utils import project_root


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
        draw_meme_text(draw, top_text.upper(), width, height, position="top")

    if bottom_text:
        draw_meme_text(draw, bottom_text.upper(), width, height, position="bottom")

    return img


def draw_meme_text(draw, text: str, width: int, height: int, position: str = "top"):
    margin_x = int(width * 0.05)
    usable_width = width - (2 * margin_x)

    font_size = int(height / 8)
    font_size = max(30, min(font_size, 120))

    best_font = None
    best_lines = []

    for size in range(font_size, 20, -5):
        try:
            font = ImageFont.truetype(f"{project_root}/utils/fonts/arial-bold.ttf", size)
        except:
            font = ImageFont.load_default()

        lines = wrap_text_to_width(draw, text, font, usable_width)

        line_height = int(size * 1.2)
        total_text_height = len(lines) * line_height

        max_text_height = (height // 2) - 40

        if total_text_height <= max_text_height:
            best_font = font
            best_lines = lines
            break
    if best_font is None:
        try:
            best_font = ImageFont.truetype(f"{project_root}/utils/fonts/arial-bold.ttf", 25)
        except:
            best_font = ImageFont.load_default()
        best_lines = wrap_text_to_width(draw, text, best_font, usable_width)

    line_height = int(best_font.size * 1.2)
    total_height = len(best_lines) * line_height

    if position == "top":
        y = 20
    else:
        y = height - total_height - 20

    outline_width = max(2, best_font.size // 15)

    for line in best_lines:
        bbox = draw.textbbox((0, 0), line, font=best_font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2

        for offset_x in range(-outline_width, outline_width + 1):
            for offset_y in range(-outline_width, outline_width + 1):
                if offset_x != 0 or offset_y != 0:
                    draw.text(
                        (x + offset_x, y + offset_y),
                        line,
                        font=best_font,
                        fill=(0, 0, 0, 255)
                    )

        draw.text((x, y), line, font=best_font, fill=(255, 255, 255, 255))
        y += line_height


def wrap_text_to_width(draw, text: str, font, max_width: int) -> list:
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        text_width = bbox[2] - bbox[0]

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