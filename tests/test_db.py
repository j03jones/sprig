import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

from recipelib.db import RecipeDB
from recipelib.mealmaster import parse_file
from recipelib.models import Ingredient, Recipe

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample.mmf"


class DBTests(unittest.TestCase):
    def setUp(self):
        self.db = RecipeDB(":memory:")

    def tearDown(self):
        self.db.close()

    def test_roundtrip(self):
        r = Recipe(title="Soup", ingredients=[Ingredient("Water", F(3, 2), "cup", group="Broth")],
                   directions="Boil.", categories=["Soup", "soup", "Easy"],
                   yield_quantity=F(2), yield_unit="servings", yield_raw="2 servings")
        rid = self.db.add_recipe(r)
        got = self.db.get_recipe(rid)
        self.assertEqual(got.title, "Soup")
        self.assertEqual(got.ingredients[0].quantity, F(3, 2))
        self.assertEqual(got.ingredients[0].group, "Broth")
        self.assertEqual(got.categories, ["Easy", "Soup"])  # case-insensitive dedupe
        self.assertEqual(got.yield_quantity, F(2))

    def test_import_skips_duplicates(self):
        recipes = parse_file(SAMPLE).recipes
        first = self.db.import_recipes(recipes)
        self.assertEqual(len(first.added), 4)
        second = self.db.import_recipes(parse_file(SAMPLE).recipes)
        self.assertEqual(len(second.added), 0)
        self.assertEqual(len(second.skipped_duplicates), 4)
        self.assertEqual(self.db.count(), 4)

    def test_search_and_category(self):
        self.db.import_recipes(parse_file(SAMPLE).recipes)
        self.assertEqual([s.title for s in self.db.list_recipes(search="garlic")],
                         ["Spaghetti With Meat Sauce"])
        self.assertEqual([s.title for s in self.db.list_recipes(search="choc cook")],
                         ["Chocolate Chip Cookies"])
        self.assertEqual([s.title for s in self.db.list_recipes(category="breakfast")], ["Pancakes"])
        self.assertEqual(self.db.list_recipes(search="zzzz"), [])
        names = [c for c, _ in self.db.list_categories()]
        self.assertIn("Pasta", names)

    def test_update_and_delete(self):
        rid = self.db.add_recipe(Recipe(title="A", ingredients=[Ingredient("x", F(1))], categories=["Old"]))
        r = self.db.get_recipe(rid)
        r.title = "B"
        r.categories = ["New"]
        r.ingredients.append(Ingredient("y", F(2), "cup"))
        self.db.update_recipe(r)
        got = self.db.get_recipe(rid)
        self.assertEqual((got.title, got.categories, len(got.ingredients)), ("B", ["New"], 2))
        self.assertEqual([c for c, _ in self.db.list_categories()], ["New"])
        self.assertEqual([s.title for s in self.db.list_recipes(search="B")], ["B"])
        self.db.delete_recipe(rid)
        self.assertIsNone(self.db.get_recipe(rid))
        self.assertEqual(self.db.list_categories(), [])

    def test_file_database_persists(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "r.db"
            with RecipeDB(path) as db:
                db.add_recipe(Recipe(title="Persist"))
            with RecipeDB(path) as db:
                self.assertEqual([s.title for s in db.list_recipes()], ["Persist"])


if __name__ == "__main__":
    unittest.main()
