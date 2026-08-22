import unittest
from datetime import date
from unittest.mock import patch

from PIL import Image

from api.routes.webhook.evolution.handles.core import clean_text
from api.routes.webhook.evolution.handles.image.sticker_caption import add_caption_to_image
from api.routes.webhook.evolution.handles.image.sticker_static import _dead_caption


class DeadStickerTests(unittest.TestCase):
    def test_dead_caption_places_memorial_on_top_and_quote_on_bottom(self):
        caption = _dead_caption(
            "últimas palavras",
            today=date(2026, 8, 22),
            birth_date=date(1501, 2, 3),
        )

        self.assertEqual(
            caption,
            "✝ RIP ✝  03/02/1501 – 22/08/2026|últimas palavras",
        )

    def test_bare_dead_parameter_is_not_rendered_as_caption(self):
        self.assertEqual(clean_text("!sticker :dead"), "")

    def test_memorial_top_can_use_smaller_text_than_epitaph(self):
        image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))

        with patch(
            "api.routes.webhook.evolution.handles.image.sticker_caption._draw_meme_text"
        ) as draw_text:
            add_caption_to_image(
                image,
                "✝ RIP ✝  03/02/1501 – 22/08/2026|últimas palavras",
                font_size_param="l",
                top_font_size_param="s",
            )

        self.assertEqual(draw_text.call_args_list[0].kwargs["size_param"], "s")
        self.assertEqual(draw_text.call_args_list[1].kwargs["size_param"], "l")


if __name__ == "__main__":
    unittest.main()
