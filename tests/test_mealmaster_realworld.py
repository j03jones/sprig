"""Patterns seen in real MealMaster archives: dash-style markers, 41-column right-hand
ingredients, '-' continuation lines, and the x/ea/ga/pg unit codes."""
import unittest
from fractions import Fraction as F
from pathlib import Path

from recipelib.mealmaster import parse_file

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "realworld.mmf"


class RealWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = parse_file(SAMPLE)
        cls.stew, cls.biscotti = cls.res.recipes

    def test_both_marker_styles(self):
        self.assertEqual([r.title for r in self.res.recipes], ["Test Stew", "Lowercase Biscotti"])
        self.assertEqual(self.res.warnings, [])

    def test_header(self):
        self.assertEqual(self.stew.yield_quantity, F(8))
        self.assertEqual(self.stew.yield_unit, "servings")
        self.assertEqual(self.stew.categories, ["Soups", "Main dish"])

    def test_ingredients_and_continuations(self):
        got = [(i.group, i.quantity, i.unit, i.item) for i in self.stew.ingredients]
        self.assertEqual(got, [
            ("", F(2), "", "Small beets thinly sliced"),         # "--" wrap, left column
            ("", F(1), "cup", "Navy beans, dry"),
            ("", F(1), "Tbsp", "Black truffles, finely choppd"),  # "-d" mid-word wrap, right column
            ("", F(1), "", "Bay leaf"),                           # x / ea codes mean "no unit"
            ("", F(1), "can", "(1 lb 13 oz) tomatoes"),
            ("SAUCE", F(1), "gallon", "Water"),
            ("SAUCE", F(1), "package", "(10 oz) raspberries"),
            ("SAUCE", F(1), "lb", "Puff pastry"),
            ("SAUCE", None, "", "Watercress for garnish"),      # item-only right field = new line
        ])

    def test_directions_stop_at_end_marker(self):
        self.assertEqual(self.stew.directions, "Simmer the stew for an hour. Serve hot.")

    def test_now_youre_cooking_export(self):
        self.assertEqual(self.biscotti.yield_quantity, F(36))
        self.assertEqual([i.item for i in self.biscotti.ingredients], ["flour", "salt", "eggs"])
        self.assertTrue(self.biscotti.directions.startswith("PREHEAT OVEN"))


if __name__ == "__main__":
    unittest.main()
