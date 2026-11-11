import unittest
from fractions import Fraction as F

from recipelib.db import RecipeDB
from recipelib.editing import (
    amount_for_editing, ingredient_from_fields, normalize_amount, recipe_from_fields,
    split_categories,
)
from recipelib.models import Ingredient, Recipe
from recipelib.render import recipe_to_html


class EditingTests(unittest.TestCase):
    def test_amount_roundtrip_is_exact(self):
        for q in (F(1), F(9, 4), F(7, 3), F(5, 16), F(33, 100)):
            ing = Ingredient("x", q, "cup")
            back = ingredient_from_fields(amount_for_editing(ing), "cup", "x")
            self.assertEqual(back.quantity, q, q)

    def test_unicode_fractions(self):
        self.assertEqual(normalize_amount("1½"), "1 1/2")
        self.assertEqual(ingredient_from_fields("½", "cup", "Sugar").quantity, F(1, 2))

    def test_unparseable_amount_is_kept_as_text(self):
        ing = ingredient_from_fields("2-3", "", "Cloves")
        self.assertIsNone(ing.quantity)
        self.assertEqual(ing.raw_quantity, "2-3")

    def test_units_normalized_and_unknown_kept(self):
        self.assertEqual(ingredient_from_fields("1", "tablespoon", "Oil").unit, "Tbsp")
        self.assertEqual(ingredient_from_fields("1", "handful", "Basil").unit, "handful")

    def test_blank_row_is_none(self):
        self.assertIsNone(ingredient_from_fields("", " ", ""))

    def test_categories(self):
        self.assertEqual(split_categories("Soup, soup , Easy,,"), ["Soup", "Easy"])

    def test_recipe_from_fields(self):
        r = recipe_from_fields(" Pie ", "Dessert", "8 servings",
                               [ingredient_from_fields("2", "cup", "Flour"), None], " Bake. ")
        self.assertEqual((r.title, r.yield_quantity, r.yield_unit), ("Pie", F(8), "servings"))
        self.assertEqual(len(r.ingredients), 1)
        self.assertEqual(r.directions, "Bake.")
        self.assertIsNone(recipe_from_fields("x", "", "", [], "").yield_quantity)


class RenderTests(unittest.TestCase):
    def test_html_escapes_and_groups(self):
        r = Recipe(title="Fish & Chips <b>", categories=["Main"], yield_quantity=F(2), yield_unit="servings",
                   ingredients=[Ingredient("Cod", F(1), "lb"), Ingredient("Salt", None, "", group="Batter")],
                   directions="Fry it.\n\nServe.")
        html = recipe_to_html(r)
        self.assertIn("Fish &amp; Chips &lt;b&gt;", html)
        self.assertIn("<h3>Batter</h3>", html)
        self.assertIn("<li>1 lb Cod</li>", html)
        self.assertIn("<p>Serve.</p>", html)


class ImportProgressTests(unittest.TestCase):
    def test_progress_and_cancel(self):
        db = RecipeDB(":memory:")
        recipes = [Recipe(title=f"R{i}", ingredients=[Ingredient(f"i{i}", F(i + 1))]) for i in range(5)]
        calls = []

        def progress(done, total):
            calls.append((done, total))
            return done < 3  # cancel after the third recipe

        summary = db.import_recipes(recipes, progress=progress)
        self.assertEqual(calls, [(1, 5), (2, 5), (3, 5)])
        self.assertEqual(len(summary.added), 3)
        self.assertEqual(db.count(), 3)


if __name__ == "__main__":
    unittest.main()
