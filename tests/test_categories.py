import unittest
from fractions import Fraction as F

from recipelib import categories
from recipelib.db import RecipeDB
from recipelib.models import Ingredient, Recipe


class MappingTests(unittest.TestCase):
    def test_common_labels(self):
        self.assertEqual(categories.groups_for(["Cakes"]), ["Desserts", "Cakes"])
        self.assertEqual(categories.groups_for(["Beef", "Soups"]), ["Soups & Stews", "Meats", "Beef"])
        self.assertEqual(categories.groups_for(["PennDutch"]), ["German & Pennsylvania Dutch"])
        self.assertEqual(categories.groups_for(["  LOWCAL "]), ["Light & Special Diets"])

    def test_source_labels_are_not_categories(self):
        self.assertEqual(categories.groups_for(["Digest", "Mar95", "Sharon"]), ["Uncategorized"])
        self.assertEqual(categories.groups_for(["Digest", "Soups"]), ["Soups & Stews"])

    def test_unknown_label_uses_patterns(self):
        self.assertEqual(categories.groups_for(["Grandma's Chicken Dishes"]), ["Poultry"])

    def test_title_is_only_a_fallback(self):
        self.assertEqual(categories.groups_for(["Digest"], "Mushroom Barley Soup"),
                         ["Soups & Stews", "Vegetables & Sides", "Pasta, Rice & Grains"])
        self.assertEqual(categories.groups_for(["Pasta"], "Chicken Soup"), ["Pasta, Rice & Grains"])

    def test_vegetarian_title_beats_meat_words(self):
        self.assertEqual(categories.groups_for([], "Veggie Burgers"), ["Vegetarian & Vegan"])

    def test_every_mapped_group_exists(self):
        from recipelib import category_data as d
        valid = set(categories.GROUP_ORDER)
        for groups in list(d.TAG_MAP.values()) + [g for _, g in d.TAG_PATTERNS] + [g for _, g in d.TITLE_RULES]:
            self.assertTrue(set(groups) <= valid, groups)
        for k, v in d.IMPLIES.items():
            self.assertTrue(k in valid and set(v) <= valid)

    def test_apply_keeps_tags_once(self):
        r = Recipe(title="X", categories=["Cakes", "Famfavorite"])
        categories.apply(r)
        self.assertEqual(r.tags, ["Cakes", "Famfavorite"])
        self.assertEqual(r.categories, ["Desserts", "Cakes"])
        categories.apply(r)  # second run must not overwrite the originals with groups
        self.assertEqual(r.tags, ["Cakes", "Famfavorite"])

    def test_sectioned_puts_unknown_groups_under_other(self):
        out = dict(categories.sectioned({"Cakes": 3, "My Own Thing": 1, "Soups & Stews": 2}))
        self.assertEqual(out["Desserts"], [("Cakes", 3)])
        self.assertEqual(out["Other"], [("My Own Thing", 1)])


def make_db():
    db = RecipeDB(":memory:")
    db.add_recipe(Recipe(title="Layer Cake", categories=["cakes", "Famfavorite"], ingredients=[Ingredient("Flour", F(2), "cup")]))
    db.add_recipe(Recipe(title="Beef Stew", categories=["Beef", "stew", "Digest"], ingredients=[Ingredient("Beef", F(1), "lb")]))
    return db


class DatabaseTests(unittest.TestCase):
    def test_regroup_keeps_original_labels_and_search(self):
        db = make_db()
        self.assertFalse(db.is_grouped())
        db.regroup_all()
        self.assertTrue(db.is_grouped())
        cake = db.get_recipe(1)
        self.assertEqual(sorted(cake.categories), ["Cakes", "Desserts"])
        self.assertEqual(cake.tags, ["cakes", "Famfavorite"])
        self.assertEqual({n for n, _ in db.list_categories()}, {"Desserts", "Cakes", "Soups & Stews", "Meats", "Beef"})
        # the old label still finds the recipe
        self.assertEqual([s.title for s in db.list_recipes(search="famfavorite")], ["Layer Cake"])
        self.assertEqual([s.title for s in db.list_recipes(category="Meats")], ["Beef Stew"])

    def test_regroup_is_repeatable(self):
        db = make_db()
        db.regroup_all(); db.regroup_all()
        self.assertEqual(db.get_recipe(1).tags, ["cakes", "Famfavorite"])
        self.assertEqual(sorted(db.get_recipe(1).categories), ["Cakes", "Desserts"])

    def test_group_spelling_is_canonical(self):
        db = RecipeDB(":memory:")
        db.add_recipe(Recipe(title="Pudding", categories=["desserts"]))  # old lower-case label
        db.regroup_all()
        self.assertEqual([n for n, _ in db.list_categories()], ["Desserts"])

    def test_restore(self):
        db = make_db()
        db.regroup_all()
        db.restore_original_categories()
        self.assertEqual(sorted(db.get_recipe(2).categories, key=str.lower), ["Beef", "Digest", "stew"])
        self.assertEqual({n for n, _ in db.list_categories()}, {"cakes", "Famfavorite", "Beef", "stew", "Digest"})

    def test_edit_keeps_tags(self):
        db = make_db()
        db.regroup_all()
        r = db.get_recipe(1)
        r.title = "Better Cake"
        db.update_recipe(r)
        self.assertEqual(db.get_recipe(1).tags, ["cakes", "Famfavorite"])

    def test_import_regroup_flag(self):
        db = RecipeDB(":memory:")
        db.import_recipes([Recipe(title="A", categories=["Cakes"])], regroup=True)
        self.assertEqual(sorted(db.get_recipe(1).categories), ["Cakes", "Desserts"])
        db.import_recipes([Recipe(title="B", categories=["Cakes"])])
        self.assertEqual(db.get_recipe(2).categories, ["Cakes"])


if __name__ == "__main__":
    unittest.main()
