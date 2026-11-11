"""tools/export_more.py: the on-demand part of the web library."""
import json
import tempfile
import unittest
from fractions import Fraction as F
from pathlib import Path

from recipelib.db import RecipeDB
from recipelib.models import Ingredient, Recipe
from tools import export_more
from tools.export_web import recipe_to_row


def recipe(title, directions, *items, cats=("Main Dishes",)):
    return Recipe(title=title, directions=directions, categories=list(cats), tags=["x"],
                  yield_quantity=F(4), yield_unit="servings",
                  ingredients=[Ingredient(item=i, quantity=F(1), unit="cup") for i in items])


STEW = ("Brown the beef in a heavy pot, add the onions and carrots, pour in the stock and simmer gently "
        "for two hours until the meat is tender, then season and serve with crusty bread.")


class ExportMore(unittest.TestCase):
    def run_export(self, core, library, *flags):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data = Path(tmp.name) / "data"
        data.mkdir()
        (data / "recipes.json").write_text(json.dumps({"v": 1, "recipes": [recipe_to_row(r) for r in core]}))
        db_path = Path(tmp.name) / "lib.db"
        with RecipeDB(db_path) as db:
            for r in library:
                db.add_recipe(r)
        self.assertEqual(export_more.main(["--db", str(db_path), "--data", str(data), *flags]), 0)
        info = json.loads((data / "more.json").read_text())
        folder = data / "more" / info["v"]
        index = json.loads((folder / "index.json").read_text())["recipes"]
        full = {}
        for path in folder.glob("??.json"):
            for row in json.loads(path.read_text())["recipes"]:
                self.assertEqual(row[0][:2], path.stem)       # each recipe is in the file named for its id
                full[row[0]] = row
        return data, info, index, full

    def test_only_recipes_not_built_in_are_exported(self):
        core = [recipe("Beef Stew", STEW, "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme")]
        library = [
            recipe("Beef Stew", STEW, "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme"),      # exact copy
            recipe("Beef Stew", STEW + " Enjoy.", "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme"),
            recipe("Lemon Tart", "Blind bake the pastry, whisk the filling, pour it in and bake until just set.",
                   "Lemons, juiced", "Eggs", "Cream", "(9 inch) pastry case", "Lemons, zested"),
        ]
        data, info, index, full = self.run_export(core, library)
        self.assertEqual(info["count"], 1)
        self.assertEqual([row[1] for row in index], ["Lemon Tart"])
        # the index has what search needs: names without amounts or preparation, each once
        self.assertEqual(index[0][3], ["Lemons", "Eggs", "Cream", "pastry case"])
        self.assertEqual(set(full), {index[0][0]})
        self.assertEqual(full[index[0][0]][7], library[2].directions)
        # without --refresh-core the built-in file is untouched
        self.assertEqual(json.loads((data / "recipes.json").read_text())["recipes"][0][7], STEW)

    def test_refresh_core_keeps_the_id(self):
        core = [recipe("Beef Stew", STEW, "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme")]
        core_id = recipe_to_row(core[0])[0]
        fixed = recipe("BEEF STEW", STEW + " Enjoy.", "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme")
        data, info, index, _ = self.run_export(core, [fixed], "--refresh-core")
        row = json.loads((data / "recipes.json").read_text())["recipes"][0]
        self.assertEqual((row[0], row[7]), (core_id, STEW + " Enjoy."))
        self.assertEqual((info["count"], index), (0, []))

    def test_rerun_replaces_the_previous_set(self):
        core = [recipe("Beef Stew", STEW, "Stewing beef", "Onions; chopped", "Carrots", "Beef stock", "Thyme")]
        tart = recipe("Lemon Tart", "Bake it.", "Lemons", "Eggs", "Cream")
        data, info, _, _ = self.run_export(core, [tart])
        self.assertEqual([p.name for p in (data / "more").iterdir()], [info["v"]])


if __name__ == "__main__":
    unittest.main()
