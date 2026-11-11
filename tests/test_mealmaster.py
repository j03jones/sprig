import unittest
from fractions import Fraction as F
from pathlib import Path

from recipelib.mealmaster import parse_file, parse_text

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample.mmf"


class ParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = parse_file(SAMPLE)
        cls.by_title = {r.title: r for r in cls.result.recipes}

    def test_finds_all_recipes(self):
        self.assertEqual(len(self.result.recipes), 4)
        self.assertEqual(self.result.warnings, [])

    def test_header_fields(self):
        r = self.by_title["Chocolate Chip Cookies"]
        self.assertEqual(r.categories, ["Cookies", "Desserts"])
        self.assertEqual(r.yield_quantity, F(48))
        self.assertEqual(r.yield_unit, "cookies")

    def test_fixed_width_ingredients(self):
        ings = self.by_title["Chocolate Chip Cookies"].ingredients
        self.assertEqual(len(ings), 7)
        self.assertEqual((ings[0].quantity, ings[0].unit, ings[0].item), (F(9, 4), "cup", "Flour"))
        self.assertEqual((ings[1].quantity, ings[1].unit), (F(1), "tsp"))
        self.assertEqual((ings[5].quantity, ings[5].unit, ings[5].item), (F(2), "", "Eggs"))

    def test_directions_unwrapped(self):
        d = self.by_title["Chocolate Chip Cookies"].directions
        self.assertTrue(d.startswith("Cream butter and sugar. Beat in the eggs."))
        self.assertEqual(len(d.split("\n\n")), 2)

    def test_groups_and_continuation(self):
        ings = self.by_title["Spaghetti With Meat Sauce"].ingredients
        self.assertEqual([i.group for i in ings], ["", "", "", "SAUCE", "SAUCE", "SAUCE", "PASTA"])
        self.assertEqual(ings[2].item, "Garlic minced")

    def test_two_column_lines(self):
        ings = self.by_title["Pancakes"].ingredients
        self.assertEqual([i.item for i in ings],
                         ["Flour", "Sugar", "Baking powder", "Salt", "Milk", "Egg", "Butter, melted"])
        self.assertEqual(ings[2].quantity, F(7, 2))

    def test_numbered_steps_stay_separate(self):
        d = self.by_title["Pancakes"].directions
        self.assertEqual(len(d.split("\n\n")), 3)

    def test_sloppy_freeform_file(self):
        r = self.by_title["Quick Guacamole"]
        self.assertEqual(r.yield_quantity, F(4))
        self.assertEqual(r.yield_unit, "servings")
        self.assertEqual([(i.quantity, i.unit, i.item) for i in r.ingredients],
                         [(F(2), "", "ripe avocados"), (F(1, 2), "cup", "chopped onion"),
                          (F(1), "Tbsp", "lime juice"), (None, "", "salt to taste")])
        self.assertTrue(r.directions.startswith("Mash avocados"))

    def test_junk_before_and_missing_end_marker(self):
        text = ("From: someone@example.com\nSubject: recipe\n\n"
                "MMMMM----- Recipe via Meal-Master (tm) v8.05\n Title: A\n\n    1 c  Sugar\n\n  Stir.\n"
                "MMMMM----- Recipe via Meal-Master (tm) v8.05\n Title: B\n\n    2 c  Flour\n\n  Bake.\nMMMMM\n")
        res = parse_text(text)
        self.assertEqual([r.title for r in res.recipes], ["A", "B"])

    def test_untitled_warns(self):
        res = parse_text("MMMMM----- Recipe via Meal-Master (tm) v8.05\n\n    1 c  Sugar\nMMMMM\n")
        self.assertEqual(res.recipes[0].title, "Untitled recipe")
        self.assertTrue(res.warnings)


if __name__ == "__main__":
    unittest.main()
