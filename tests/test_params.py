import unittest

from services.params import parse_params


class ParseParamsTests(unittest.TestCase):
    def test_bare_parameter_inverts_false_default(self):
        self.assertEqual(parse_params("!sticker :no-background"), {"no-background": True})

    def test_dead_works_as_bare_or_explicit_parameter(self):
        self.assertEqual(parse_params("!sticker :dead"), {"dead": True})
        self.assertEqual(parse_params("!sticker :dead=t"), {"dead": "t"})

    def test_no_color_works_as_bare_or_explicit_parameter(self):
        self.assertEqual(parse_params("!sticker :no-color"), {"no-color": True})
        self.assertEqual(parse_params("!sticker :no-color=t"), {"no-color": "t"})

    def test_bare_parameter_without_default_is_true(self):
        self.assertEqual(parse_params("!sticker :effect"), {"effect": True})

    def test_explicit_parameter_value_still_works(self):
        self.assertEqual(parse_params("!sticker :no-background=t"), {"no-background": "t"})

    def test_bare_and_explicit_parameters_can_be_mixed(self):
        self.assertEqual(
            parse_params("!sticker :no-background :blur=25"),
            {"no-background": True, "blur": 25},
        )

    def test_parameter_name_must_match_completely(self):
        self.assertEqual(parse_params("!sticker :no-background-extra"), {})


if __name__ == "__main__":
    unittest.main()
