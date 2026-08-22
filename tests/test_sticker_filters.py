import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from api.routes.webhook.evolution.handles.image.sticker_animated import (
    _remove_color_from_animation,
)
from api.routes.webhook.evolution.handles.image.sticker_filters import remove_color


class StickerFilterTests(unittest.TestCase):
    def test_remove_color_preserves_alpha(self):
        image = Image.new("RGBA", (1, 1), (200, 100, 50, 123))

        result = remove_color(image)

        red, green, blue, alpha = result.getpixel((0, 0))
        self.assertEqual(red, green)
        self.assertEqual(green, blue)
        self.assertEqual(alpha, 123)

    def test_remove_color_is_applied_to_every_animation_frame(self):
        with TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.gif"
            output_path = Path(temp_dir) / "output.gif"
            frames = [
                Image.new("RGB", (2, 2), (255, 0, 0)),
                Image.new("RGB", (2, 2), (0, 0, 255)),
            ]
            frames[0].save(
                input_path,
                save_all=True,
                append_images=frames[1:],
                duration=[50, 50],
                loop=0,
            )

            _remove_color_from_animation(str(input_path), str(output_path))

            with Image.open(output_path) as result:
                self.assertEqual(result.n_frames, 2)
                for frame_index in range(result.n_frames):
                    result.seek(frame_index)
                    red, green, blue = result.convert("RGB").getpixel((0, 0))
                    self.assertEqual(red, green)
                    self.assertEqual(green, blue)


if __name__ == "__main__":
    unittest.main()
