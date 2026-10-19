import os
import unittest
from io import BytesIO
from unittest.mock import patch

import numpy as np
from PIL import Image

from api.routes.webhook.waha.handles.image import sticker_animated as animated
from services.params import parse_params


class StickerEffectControlTests(unittest.TestCase):
    def test_parameters_are_parsed_and_removed_from_caption(self):
        from api.routes.webhook.waha.handles.core import clean_text

        command = "!sticker :effect=explosion :size=0.5 :duration=2 legenda"
        self.assertEqual(parse_params(command), {
            "effect": "explosion", "size": 0.5, "duration": 2,
        })
        self.assertEqual(clean_text(command), "legenda")

    def test_smaller_bulge_leaves_pixels_outside_its_radius_unchanged(self):
        pixels = np.arange(32 * 32 * 3, dtype=np.uint8).reshape(32, 32, 3)
        source = Image.fromarray(pixels)
        small = np.array(animated._apply_bulge_effect(source, size=0.25))
        normal = np.array(animated._apply_bulge_effect(source))
        np.testing.assert_array_equal(small[8, 16], pixels[8, 16])
        self.assertFalse(np.array_equal(normal[8, 16], pixels[8, 16]))

    def test_explosion_size_changes_overlay_and_keeps_it_centered(self):
        source = Image.new("RGBA", (100, 100))
        overlay = Image.new("RGBA", (10, 10), "red")
        small = animated._apply_explosion_effect(source, 0, [overlay], size=0.5)
        normal = animated._apply_explosion_effect(source, 0, [overlay])
        large = animated._apply_explosion_effect(source, 0, [overlay], size=3)
        self.assertEqual(small.getbbox(), (34, 34, 66, 66))
        self.assertEqual(normal.getbbox(), (17, 17, 82, 82))
        self.assertEqual(large.getbbox(), (0, 0, 100, 100))

    def test_invalid_numbers_fall_back_and_extremes_are_bounded(self):
        for value in (None, True, "invalid", "nan", "inf"):
            self.assertEqual(animated._bounded_effect_number(value, 1, 0.1, 3), 1)
        self.assertEqual(animated._bounded_effect_number(-2, 1, 0.1, 3), 0.1)
        self.assertEqual(animated._bounded_effect_number(100, 1, 0.1, 3), 3)

    def test_explosion_duration_controls_source_timeline_and_respects_cut(self):
        source = BytesIO()
        Image.new("RGB", (16, 16), "white").save(source, format="PNG")
        for duration, cut, expected in ((2, None, 2), (100, None, 7), (5, "1-2", 2)):
            with (
                self.subTest(duration=duration, cut=cut),
                patch.object(animated.subprocess, "run") as ffmpeg,
                patch.object(animated, "_add_effect_to_gif_frames",
                             side_effect=lambda source, output, *args, **kwargs: output) as add_effect,
                patch.object(animated, "_compress_webp_sticker") as compress,
            ):
                _, paths = animated._build_animated_sticker_webp(
                    source.getvalue(), effect="explosion", effect_size=0.5,
                    duration=duration, cut_spec=cut, speed=2,
                )
                try:
                    args = ffmpeg.call_args.args[0]
                    self.assertEqual(float(args[args.index("-t") + 1]), expected)
                    self.assertEqual(float(args[args.index("-loop") - 1]), expected)
                    self.assertEqual(add_effect.call_args.kwargs["effect_size"], 0.5)
                    self.assertEqual(add_effect.call_args.kwargs["effect_speed"], 2)
                    self.assertEqual(compress.call_args.kwargs["duration"], expected)
                finally:
                    for path in paths:
                        if os.path.exists(path):
                            os.remove(path)


if __name__ == "__main__":
    unittest.main()
