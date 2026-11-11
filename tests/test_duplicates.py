import unittest
from fractions import Fraction

from recipelib import duplicates as D
from recipelib.db import RecipeDB
from recipelib.models import Ingredient, Recipe


def mk(title, items, directions, cats=(), tags=()):
    return Recipe(title=title, ingredients=[Ingredient(item=i, quantity=Fraction(1), unit="cup") for i in items],
                  directions=directions, categories=list(cats), tags=list(tags))


CAKE = ["flour", "sugar", "butter", "eggs", "vanilla extract", "baking powder", "milk"]
CAKE_DIR = "Cream the butter and sugar. Beat in eggs and vanilla. Fold in flour and baking powder alternately with milk. Bake until golden."
SOUP = ["leeks", "potatoes", "chicken stock", "cream", "chives", "nutmeg", "pepper"]
SOUP_DIR = "Simmer the leeks and potatoes in stock until soft, puree, stir in cream and season with nutmeg and pepper."


class Classify(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(D.classify(1.0, 0.0, 0.9), D.HIGH)          # retitled copy
        self.assertEqual(D.classify(0.95, 1.0, 0.1), D.LIKELY)       # same title, rewritten directions
        self.assertEqual(D.classify(0.7, 0.8, 0.0), D.POSSIBLE)      # variation
        self.assertIsNone(D.classify(0.7, 0.0, 0.05))                # merely similar dish
        self.assertIsNone(D.classify(0.3, 1.0, 1.0))                 # same title, different ingredients


class Finder(unittest.TestCase):
    def setUp(self):
        a = mk("Vanilla Cake", CAKE, CAKE_DIR); a.id = 1
        b = mk("VANILLA CAKE (my mom's)", CAKE, CAKE_DIR + " Cool."); b.id = 2
        c = mk("Leek Soup", SOUP, SOUP_DIR); c.id = 3
        d = mk("Leek and Potato Soup", SOUP, SOUP_DIR); d.id = 4
        e = mk("Vanilla Cake", ["rice", "saffron", "lamb", "yogurt", "mint"], "Cook the lamb with rice."); e.id = 5
        self.recipes = [a, b, c, d, e]

    def test_groups(self):
        groups = D.find_duplicate_groups(self.recipes)
        self.assertEqual(sorted(sorted(g.ids) for g in groups), [[1, 2], [3, 4]])
        self.assertTrue(all(g.level == D.HIGH for g in groups))

    def test_keeper_is_fullest_copy(self):
        g = [g for g in D.find_duplicate_groups(self.recipes) if 1 in g.ids][0]
        self.assertEqual(g.keep_id, 2)    # longer directions

    def test_ignored_pairs(self):
        self.assertEqual([sorted(g.ids) for g in D.find_duplicate_groups(self.recipes, ignored=[(2, 1)])], [[3, 4]])


class WithDB(unittest.TestCase):
    def make(self):
        db = RecipeDB(":memory:")
        a = db.add_recipe(mk("Vanilla Cake", CAKE, CAKE_DIR, cats=["Cakes"], tags=["cakes"]))
        b = db.add_recipe(mk("Vanilla Cake!", CAKE, CAKE_DIR + " Cool.", cats=["Desserts"], tags=["party"]))
        c = db.add_recipe(mk("Leek Soup", SOUP, SOUP_DIR))
        return db, a, b, c

    def test_scan_and_merge(self):
        db, a, b, c = self.make()
        groups = D.scan(db)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g.keep_id, b)
        self.assertEqual(D.merge_group(db, g.keep_id, g.ids[1:]), 1)
        self.assertEqual(db.count(), 2)
        kept = db.get_recipe(b)
        self.assertEqual(sorted(kept.categories), ["Cakes", "Desserts"])
        self.assertEqual(sorted(kept.tags), ["cakes", "party"])
        self.assertEqual(D.scan(db), [])

    def test_ignore_survives_rescan(self):
        db, a, b, c = self.make()
        D.ignore_group(db, [a, b])
        self.assertEqual(D.scan(db), [])

    def test_report_text(self):
        db, a, b, c = self.make()
        text = D.report(D.scan(db), db)
        self.assertIn("1 duplicate groups", text)
        self.assertIn("Vanilla Cake", text)


if __name__ == "__main__":
    unittest.main()
