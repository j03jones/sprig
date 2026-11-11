import json
import shutil
import subprocess
import unittest
from fractions import Fraction
from pathlib import Path

from recipelib import link_data
from recipelib.db import RecipeDB
from recipelib.formatting import credit_line, format_ingredient, format_yield, recipe_to_text
from recipelib.render import recipe_to_html
from recipelib.webimport import (
    ImportError_, check_url, collection_for, find_recipe_node, parse_ingredient_line, recipe_from_html,
    recipe_from_schema, site_name_from_html,
)

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "tests" / "fixtures" / "webimport_page.html").read_text(encoding="utf-8")
URL = "https://example.com/made-up-lentil-stew/"


class IngredientLines(unittest.TestCase):
    def test_amounts_units_items(self):
        cases = {
            "1 1/2 cups dried lentils": (Fraction(3, 2), "", "cup", "dried lentils"),
            "½ teaspoon salt": (Fraction(1, 2), "", "tsp", "salt"),
            "1½ tbsp oil": (Fraction(3, 2), "", "Tbsp", "oil"),
            "2-3 cloves garlic, minced": (None, "2-3", "clove", "garlic, minced"),
            "1 (14 oz) can tomatoes": (Fraction(1), "", "", "(14 oz) can tomatoes"),
            "Pepper to taste": (None, "", "", "Pepper to taste"),
            "1 cup of water": (Fraction(1), "", "cup", "water"),
            "2 &amp; a bit <b>carrots</b>": (Fraction(2), "", "", "& a bit carrots"),
        }
        for line, (q, raw, unit, item) in cases.items():
            ing = parse_ingredient_line(line)
            self.assertEqual((ing.quantity, ing.raw_quantity, ing.unit, ing.item), (q, raw, unit, item), line)

    def test_blank(self):
        self.assertIsNone(parse_ingredient_line("  "))


class FromPage(unittest.TestCase):
    def setUp(self):
        self.r = recipe_from_html(PAGE, URL)

    def test_content_and_credit(self):
        r = self.r
        self.assertEqual(r.title, "Made-up Lentil Stew & Greens")
        self.assertEqual(len(r.ingredients), 6)
        self.assertEqual(r.directions, "Stew:\nRinse the lentils.\nSimmer everything for 25 minutes.\nSeason and serve.")
        self.assertEqual((r.yield_quantity, r.yield_unit), (Fraction(4), "bowls"))
        self.assertEqual((r.source_author, r.source_name, r.source_url), ("Pat Example", "Test Kitchen Blog", URL))
        self.assertIn("Vegetarian & Vegan", r.categories)
        self.assertEqual(r.tags, ["Soup", "American"])

    def test_story_and_photos_are_not_taken(self):
        text = recipe_to_text(self.r)
        self.assertNotIn("long story", text)
        self.assertNotIn("photo.jpg", text)

    def test_credit_shown(self):
        self.assertEqual(credit_line(self.r), "Recipe by Pat Example, Test Kitchen Blog")
        self.assertIn("Recipe by Pat Example, Test Kitchen Blog\nOriginal: " + URL, recipe_to_text(self.r))
        html = recipe_to_html(self.r)
        self.assertIn(f'href="{URL}"', html)
        self.assertIn("Pat Example", html)

    def test_no_recipe(self):
        with self.assertRaises(ImportError_):
            recipe_from_html("<html><body>nothing</body></html>", URL)

    def test_site_name(self):
        self.assertEqual(site_name_from_html(PAGE), "Test Kitchen Blog")

    def test_known_collection_fills_credit_and_vegan(self):
        node = {"@type": "Recipe", "name": "Some dish", "recipeIngredient": ["1 cup rice"]}
        r = recipe_from_schema(node, "https://www.noracooks.com/some-dish/")
        self.assertEqual((r.source_author, r.source_name), ("Nora Taylor", "Nora Cooks"))
        self.assertIn("Vegetarian & Vegan", r.categories)
        self.assertIsNotNone(collection_for("https://noracooks.com/x/"))
        self.assertIsNone(collection_for("https://example.com/x/"))

    def test_check_url(self):
        self.assertEqual(check_url("example.com/a"), "https://example.com/a")
        for bad in ("ftp://x.com/a", "javascript:alert(1)", ""):
            with self.assertRaises(ImportError_):
                check_url(bad)


class StoredCredit(unittest.TestCase):
    def test_round_trip_and_old_files(self):
        db = RecipeDB()
        rid = db.add_recipe(recipe_from_html(PAGE, URL))
        got = db.get_recipe(rid)
        self.assertEqual((got.source_author, got.source_name, got.source_url), ("Pat Example", "Test Kitchen Blog", URL))
        got.source_author = "P. Example"
        db.update_recipe(got)
        self.assertEqual(db.get_recipe(rid).source_author, "P. Example")

    def test_library_file_from_before_credit_columns(self):
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            con = sqlite3.connect(path)
            con.executescript("CREATE TABLE recipes (id INTEGER PRIMARY KEY, title TEXT NOT NULL, directions TEXT NOT NULL DEFAULT '', "
                              "yield_qty TEXT, yield_unit TEXT NOT NULL DEFAULT '', yield_raw TEXT NOT NULL DEFAULT '', "
                              "content_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
                              "INSERT INTO recipes(title, content_hash, created_at, updated_at) VALUES ('Old', 'x', 'n', 'n');")
            con.commit(); con.close()
            with RecipeDB(path) as db:
                r = db.get_recipe(1)
                self.assertEqual((r.title, r.source_url), ("Old", ""))
                self.assertFalse(r.has_source)


class LinkList(unittest.TestCase):
    def test_links_are_titles_and_search_links_only(self):
        data = link_data.as_json()
        nora = data[0]
        self.assertEqual((nora["author"], nora["site"]), ("Nora Taylor", "Nora Cooks"))
        for _section, rows in nora["sections"]:
            for title, link in rows:
                self.assertTrue(link.startswith("https://www.noracooks.com/?s="), link)
                self.assertTrue(title)

    def test_web_copy_is_current(self):
        js = (ROOT / "web" / "js" / "linkdata.js").read_text(encoding="utf-8")
        start = js.index("[")
        self.assertEqual(json.loads(js[start:js.rindex("]") + 1]), link_data.as_json(),
                         "run python3 tools/gen_unitdata.py")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SameInJavaScript(unittest.TestCase):
    def js(self, node, url, site=""):
        out = subprocess.run(["node", str(ROOT / "tools" / "webimport_js.mjs")], input=json.dumps(
            {"node": node, "url": url, "site": site}), capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_matches_python(self):
        nodes = [
            (find_recipe_node(PAGE), URL, "Test Kitchen Blog"),
            ({"@type": "Recipe", "name": "Dish", "recipeYield": 6, "recipeInstructions": "Mix.\n\nBake.",
              "recipeIngredient": ["2 to 3 tbsp sugar", "1/4 tsp salt", "3 large carrots"]},
             "https://www.noracooks.com/dish/", ""),
            ({"@type": ["Recipe"], "name": "X", "author": [{"name": "A"}, "B"], "publisher": {"name": "P"}}, "", ""),
        ]
        for node, url, site in nodes:
            r = recipe_from_schema(node, url, site)
            py = {"title": r.title, "ings": [format_ingredient(i) for i in r.ingredients], "dir": r.directions,
                  "yield": format_yield(r), "tags": r.tags, "author": r.source_author, "site": r.source_name,
                  "url": r.source_url, "vegan": "Vegetarian & Vegan" in r.categories}
            self.assertEqual(self.js(node, url, site), py)


if __name__ == "__main__":
    unittest.main()
