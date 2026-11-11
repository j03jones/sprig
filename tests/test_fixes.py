"""Importer fixes (encodings, wrapped lines, rules, ranges), range scaling, unit conversion,
MealMaster export, the shopping list, and the large-library database fixes."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction as F
from pathlib import Path

from recipelib import convert, pantry, shopping
from recipelib.__main__ import main
from recipelib.db import RecipeDB
from recipelib.formatting import format_ingredient
from recipelib.mealmaster import decode_bytes, parse_text, recipe_to_mmf, recipes_to_mmf
from recipelib.models import Ingredient, Recipe
from recipelib.scaling import scale_recipe
from recipelib.units import parse_range

HEAD = "MMMMM----- Recipe via Meal-Master (tm) v8.05\n\n      Title: T\n Categories: Test\n      Yield: 4 servings\n\n"


def one(body: str) -> Recipe:
    return parse_text(HEAD + body + "\nMMMMM\n").recipes[0]


class Encodings(unittest.TestCase):
    def test_dos_degree_sign_and_fraction(self):
        text = decode_bytes(b"Bake at 350\xf8F for 2\xab hours. Saut\x82 the onions.")
        self.assertEqual(text, "Bake at 350°F for 2½ hours. Sauté the onions.")

    def test_windows_text_is_kept(self):
        text = decode_bytes("Sauté at 350°F, don’t stir ½ cup".encode("cp1252"))
        self.assertEqual(text, "Sauté at 350°F, don’t stir ½ cup")

    def test_utf8_first(self):
        self.assertEqual(decode_bytes("crème brûlée".encode("utf-8")), "crème brûlée")

    def test_mixed_file_is_decided_line_by_line(self):
        data = b"Bake at 350\xf8F.\n" + "Sauté the onions.\n".encode("cp1252")
        self.assertEqual(decode_bytes(data), "Bake at 350°F.\nSauté the onions.\n")

    def test_dos_padding_bytes_become_spaces(self):
        self.assertEqual(decode_bytes(b"\xff\xff\xff\xff\xff\xff1 c  Flour"), "      1 c  Flour")


class WrappedLines(unittest.TestCase):
    def test_short_line_wrap_is_a_new_word(self):
        r = one("      2 ts Butter\n           -salt and pepper\n\n  Mix.\n")
        self.assertEqual(r.ingredients[0].item, "Butter salt and pepper")

    def test_full_line_wrap_continues_the_word(self):
        r = one("      1 tb Black truffles, finely chopp\n           -d\n\n  Mix.\n")
        self.assertEqual(r.ingredients[0].item, "Black truffles, finely choppd")

    def test_full_line_ending_on_a_whole_word(self):
        r = one("      1 c  Raspberries for garnish and\n           -ccompaniment\n\n  Mix.\n")
        self.assertEqual(r.ingredients[0].item, "Raspberries for garnish and ccompaniment")


class Directions(unittest.TestCase):
    def test_rules_dropped_and_headings_kept(self):
        r = one("      1 c  Flour\n\n  Note about flour.\n  ~-------------------------------\n"
                "  ~--- Mix well.\n  ---------For the sauce:----------\n  Stir. -----\n")
        self.assertEqual(r.directions, "Note about flour.\n\nMix well.\n\nFor the sauce:\n\nStir.")

    def test_hyphenated_words_survive(self):
        r = one("      1 c  Flour\n\n  Use a well-seasoned, deep-sided pan -- carefully.\n")
        self.assertEqual(r.directions, "Use a well-seasoned, deep-sided pan -- carefully.")


class Ranges(unittest.TestCase):
    def test_parse_range(self):
        self.assertEqual(parse_range("2-3"), (F(2), F(3)))
        self.assertEqual(parse_range("1/2 to 1"), (F(1, 2), F(1)))
        self.assertEqual(parse_range("1 1/2-2"), (F(3, 2), F(2)))
        self.assertIsNone(parse_range("1-1/2"))      # that is "one and a half", not a range
        self.assertIsNone(parse_range("a few"))

    def test_mealmaster_to_range(self):
        r = one("    1/2 c  To 1 c Dry sherry\n  1 1/2 lb To 3 lb Frying chicken\n      2 c  Tomatoes\n\n  Mix.\n")
        self.assertEqual([format_ingredient(i) for i in r.ingredients],
                         ["1/2-1 cup Dry sherry", "1 1/2-3 lb Frying chicken", "2 cups Tomatoes"])
        self.assertIsNone(r.ingredients[0].quantity)

    def test_ranges_scale(self):
        r = Recipe(title="x", yield_quantity=F(4), ingredients=[
            Ingredient(item="flour", unit="cup", raw_quantity="2-3"),
            Ingredient(item="salt", raw_quantity="to taste")])
        res = scale_recipe(r, factor=2)
        self.assertEqual(format_ingredient(res.recipe.ingredients[0]), "4-6 cups flour")
        self.assertEqual(len(res.warnings), 1)        # only "to taste" can't be scaled
        half = scale_recipe(r, factor=F(1, 2)).recipe.ingredients[0]
        self.assertEqual(format_ingredient(half), "1-1 1/2 cups flour")


class Conversion(unittest.TestCase):
    def test_to_metric(self):
        cases = [((F(1), "cup"), (F(240), "ml")), ((F(1), "Tbsp"), (F(15), "ml")), ((F(1), "tsp"), (F(5), "ml")),
                 ((F(8), "oz"), (F(230), "g")), ((F(5, 2), "lb"), (F(23, 20), "kg")), ((F(2), "can"), (F(2), "can"))]
        for given, want in cases:
            self.assertEqual(convert.convert_amount(*given, "metric"), want)

    def test_to_us(self):
        cases = [((F(250), "ml"), (F(1), "cup")), ((F(5), "ml"), (F(1), "tsp")), ((F(15), "ml"), (F(1), "Tbsp")),
                 ((F(100), "g"), (F(7, 2), "oz")), ((F(1), "kg"), (F(9, 4), "lb")), ((F(3), "cup"), (F(3), "cup"))]
        for given, want in cases:
            self.assertEqual(convert.convert_amount(*given, "us"), want)

    def test_recipe_copy(self):
        r = Recipe(title="x", ingredients=[Ingredient(item="milk", quantity=F(1), unit="cup"),
                                           Ingredient(item="salt", raw_quantity="2-3", unit="tsp")])
        m = convert.convert_recipe(r, "metric")
        self.assertEqual([format_ingredient(i) for i in m.ingredients], ["240 ml milk", "2-3 tsp salt"])
        self.assertEqual(r.ingredients[0].unit, "cup")
        with self.assertRaises(ValueError):
            convert.convert_recipe(r, "imperial")


class Export(unittest.TestCase):
    def test_round_trip(self):
        r = Recipe(title="Garlic Chicken", categories=["Poultry", "Main dish"], yield_quantity=F(6), yield_unit="servings",
                   directions="Brown the chicken.\nAdd everything else and simmer for an hour, stirring now and then until it is done.",
                   ingredients=[
                       Ingredient(item="Chicken thighs, boneless and skinless, trimmed of all visible fat", quantity=F(3, 2), unit="lb"),
                       Ingredient(item="garlic", quantity=F(4), unit="clove"),
                       Ingredient(item="Dry sherry", raw_quantity="1/2-1", unit="cup"),
                       Ingredient(item="Salt to taste"),
                       Ingredient(item="Cream", quantity=F(1, 3), unit="cup", group="Sauce")])
        back = parse_text(recipe_to_mmf(r)).recipes[0]
        self.assertEqual((back.title, back.categories, back.yield_quantity, back.yield_unit),
                         (r.title, r.categories, r.yield_quantity, r.yield_unit))
        self.assertEqual([format_ingredient(i) for i in back.ingredients],
                         ["1 1/2 lb Chicken thighs, boneless and skinless, trimmed of all visible fat",
                          "4 cloves garlic", "1/2-1 cup Dry sherry", "Salt to taste", "1/3 cup Cream"])
        self.assertEqual(back.ingredients[-1].group.lower(), "sauce")
        self.assertEqual(back.directions.replace("\n\n", "\n"), r.directions)

    def test_lines_fit_mealmaster_columns(self):
        r = Recipe(title="x", ingredients=[Ingredient(item="word " * 20, quantity=F(1), unit="cup")])
        for line in recipe_to_mmf(r).splitlines():
            self.assertLessEqual(len(line), 79)

    def test_several(self):
        rs = [Recipe(title=f"R{n}", ingredients=[Ingredient(item="egg", quantity=F(n))], directions="Cook.") for n in (1, 2, 3)]
        self.assertEqual([r.title for r in parse_text(recipes_to_mmf(rs)).recipes], ["R1", "R2", "R3"])


class ShoppingList(unittest.TestCase):
    def recipes(self):
        a = Recipe(title="A", ingredients=[
            Ingredient(item="Onions; finely chopped", quantity=F(2)),
            Ingredient(item="Flour", quantity=F(1), unit="cup"),
            Ingredient(item="Butter", quantity=F(8), unit="oz"),
            Ingredient(item="Salt", quantity=F(1), unit="tsp"),
            Ingredient(item="(10 oz) tomatoes", quantity=F(1), unit="can"),
            Ingredient(item="Parsley", raw_quantity="2-3", unit="Tbsp")])
        b = Recipe(title="B", ingredients=[
            Ingredient(item="onion, sliced", quantity=F(1)),
            Ingredient(item="flour", quantity=F(4), unit="Tbsp"),
            Ingredient(item="butter", quantity=F(1), unit="lb"),
            Ingredient(item="salt", quantity=F(2), unit="tsp"),
            Ingredient(item="Flour", quantity=F(500), unit="g"),
            Ingredient(item="Pepper to taste")])
        return a, b

    def test_combine(self):
        text = shopping.to_text(shopping.combine(self.recipes()))
        self.assertEqual(text.splitlines(), [
            "[ ] Butter: 1 1/2 lb", "[ ] Flour: 1 1/4 cups + 500 g", "[ ] Onions: 3", "[ ] Parsley: 2-3 Tbsp",
            "[ ] Pepper to taste", "[ ] Salt: 1 Tbsp", "[ ] Tomatoes: 1 can"])

    def test_scaled_and_sources(self):
        a, b = self.recipes()
        lines = {l.key: l for l in shopping.shopping_list([(a, F(2)), (b, F(1))])}
        self.assertEqual(lines["onion"].amounts, ["5"])
        self.assertEqual(lines["onion"].recipes, ["A", "B"])
        self.assertEqual(lines["parsley"].notes, ["4-6 Tbsp"])

    def test_aisles(self):
        cases = {"Onions; chopped": "Produce", "Chicken broth": "Pantry", "Peanut butter": "Pantry",
                 "Garlic powder": "Spices & Seasonings", "Green pepper, diced": "Produce",
                 "Red pepper flakes": "Spices & Seasonings", "Ice cream": "Frozen", "Chicken breasts": "Meat & Seafood",
                 "Cream cheese": "Dairy & Eggs", "All-purpose flour": "Baking", "Bread crumbs": "Bakery",
                 "Dry white wine": "Drinks", "paper towels": "Other"}
        for name, aisle in cases.items():
            self.assertEqual(shopping.aisle_for(name), aisle, name)
        groups = shopping.by_aisle(shopping.combine(self.recipes()))
        self.assertEqual([a for a, _ in groups], [a for a in shopping.AISLE_ORDER if a in dict(groups)])
        self.assertEqual(sum(len(g) for _, g in groups), 7)

    def test_keys(self):
        self.assertEqual(shopping.item_key("Cherry Tomatoes, halved"), "cherry tomato")
        self.assertEqual(shopping.item_key("Berries (fresh)"), "berry")
        self.assertEqual(shopping.item_key("Swiss cheese"), "swiss cheese")


class WhatCanIMake(unittest.TestCase):
    def recipes(self):
        def r(title, *items):
            return Recipe(title=title, ingredients=[Ingredient(item=i) for i in items])
        return [r("Fried rice", "Cooked rice", "Eggs; beaten", "Soy sauce", "Green onions, sliced", "Oil"),
                r("Omelette", "Eggs", "Butter", "Salt", "Pepper"),
                r("Soy milk pudding", "Soy milk", "Sugar", "Cornstarch"),
                r("Roast chicken", "Whole chicken", "Lemon", "Thyme", "Garlic", "Butter"),
                r("Plain rice", "Rice"),
                r("Rice and eggs", "Rice", "Eggs", "Eggs; extra")]

    def test_ranked_by_what_is_missing(self):
        found = pantry.match(self.recipes(), ["rice", "eggs", "soy sauce"])
        self.assertEqual([(m.recipe.title, m.missing) for m in found],
                         [("Rice and eggs", []), ("Omelette", []), ("Fried rice", ["Green onions"])])

    def test_whole_term_must_match(self):
        # "soy sauce" is not "soy milk"; a one-ingredient recipe is not listed
        titles = [m.recipe.title for m in pantry.match(self.recipes(), ["soy sauce", "rice"], max_missing=3)]
        self.assertNotIn("Soy milk pudding", titles)
        self.assertNotIn("Plain rice", titles)

    def test_basics_and_limits(self):
        with_basics = pantry.match(self.recipes(), ["eggs"], max_missing=0)
        without = pantry.match(self.recipes(), ["eggs"], max_missing=0, assume_staples=False)
        self.assertEqual([m.recipe.title for m in with_basics], ["Omelette"])
        self.assertEqual(without, [])
        self.assertEqual(pantry.match(self.recipes(), []), [])
        self.assertEqual(len(pantry.match(self.recipes(), ["chicken", "lemon", "thyme", "garlic"], limit=1)), 1)


class BigLibrary(unittest.TestCase):
    def test_search_matching_thousands(self):
        db = RecipeDB()
        db.import_recipes(Recipe(title=f"Soup {n}", ingredients=[Ingredient(item="salt", quantity=F(n))])
                          for n in range(1, 2001))
        self.assertEqual(len(db.list_recipes(search="soup")), 2000)
        self.assertEqual(len(db.list_recipes(search="soup", limit=10)), 10)
        self.assertEqual(db.list_recipes(search="nothing"), [])
        db.close()

    def test_categories_listed_for_long_and_short_lists(self):
        db = RecipeDB()
        db.import_recipes(Recipe(title=f"Soup {n}", categories=["Soups", "Winter"]) for n in range(60))
        self.assertEqual(db.list_recipes()[0].categories, ["Soups", "Winter"])
        self.assertEqual(db.list_recipes(limit=3)[0].categories, ["Soups", "Winter"])
        db.close()

    def test_import_stops_early_but_keeps_what_was_added(self):
        db = RecipeDB()
        s = db.import_recipes((Recipe(title=f"R{n}") for n in range(10)), progress=lambda done, total: done < 4)
        self.assertEqual((len(s.added), db.count()), (4, 4))
        db.close()


class CommandLine(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_import_folder_export_shopping(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "lib.db")
            folder = Path(tmp) / "in"
            (folder / "sub").mkdir(parents=True)
            sample = Path(__file__).resolve().parent.parent / "samples" / "sample.mmf"
            (folder / "a.MMF").write_bytes(sample.read_bytes())
            (folder / "sub" / "b.txt").write_bytes(sample.read_bytes())
            (folder / "notes.doc").write_text("not a recipe file")
            code, out, _ = self.run_cli("--db", db, "import", str(folder))
            self.assertEqual(code, 0)
            self.assertIn("from 2 files", out)
            self.assertIn("duplicates skipped", out)

            code, _, err = self.run_cli("--db", db, "import", str(Path(tmp) / "missing.mmf"))
            self.assertEqual(code, 1)
            self.assertIn("no such file or folder", err)

            dest = str(Path(tmp) / "out.mmf")
            code, out, _ = self.run_cli("--db", db, "export", "-o", dest)
            self.assertEqual(code, 0)
            with RecipeDB(db) as lib:
                self.assertEqual(len(parse_text(Path(dest).read_text(encoding="utf-8")).recipes), lib.count())

            code, out, _ = self.run_cli("--db", db, "shopping", "1", "2:2")
            self.assertEqual(code, 0)
            self.assertIn("[ ] ", out)
            self.assertEqual(self.run_cli("--db", db, "shopping", "1:zero")[0], 1)
            self.assertEqual(self.run_cli("--db", db, "show", "1", "--units", "metric")[0], 0)


if __name__ == "__main__":
    unittest.main()


class TidyTitles(unittest.TestCase):
    def test_capitals_become_title_case(self):
        from recipelib.tidy import tidy_title
        cases = {
            "PEPPERY RICE": "Peppery Rice",
            "MOM'S BBQ RIBS WITH SAUCE": "Mom's BBQ Ribs with Sauce",
            "HORS D'OEUVRES A LA KING": "Hors D'Oeuvres a la King",
            "STIR-FRY: THE BASICS": "Stir-Fry: The Basics",
            "O'BRIEN POTATOES II": "O'Brien Potatoes II",
            "VEAL ROUNDS (WITH VEGETABLES)": "Veal Rounds (With Vegetables)",
            "THE BEST CHILI": "The Best Chili",
        }
        for given, want in cases.items():
            self.assertEqual(tidy_title(given), want)

    def test_other_titles_are_left_alone(self):
        from recipelib.tidy import tidy_title
        for title in ["Coq au Vin", "BBQ", "Mom's BBQ Ribs", "mixed CASE Title", "", "1-2-3"]:
            self.assertEqual(tidy_title(title), title)
