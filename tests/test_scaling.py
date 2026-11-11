import unittest
from fractions import Fraction as F

from recipelib.formatting import format_ingredient
from recipelib.models import Ingredient, Recipe
from recipelib.scaling import scale_recipe


def make():
    return Recipe(
        title="T",
        ingredients=[
            Ingredient("Flour", F(2), "cup"),
            Ingredient("Baking powder", F(1), "tsp"),
            Ingredient("Butter", F(4), "Tbsp"),
            Ingredient("Eggs", F(2)),
            Ingredient("Salt to taste"),
            Ingredient("Cheese", None, "", raw_quantity="2-3"),
            Ingredient("Beef", F(8), "oz"),
        ],
        yield_quantity=F(4), yield_unit="servings",
    )


class ScalingTests(unittest.TestCase):
    def test_double(self):
        res = scale_recipe(make(), factor=2)
        text = [format_ingredient(i) for i in res.recipe.ingredients]
        self.assertEqual(text[0], "4 cups Flour")
        self.assertEqual(text[1], "2 tsp Baking powder")
        self.assertEqual(text[2], "1/2 cup Butter")  # 8 Tbsp promoted
        self.assertEqual(text[3], "4 Eggs")
        self.assertEqual(text[4], "Salt to taste")
        self.assertEqual(text[6], "1 lb Beef")  # 16 oz promoted
        self.assertEqual(res.recipe.yield_quantity, F(8))
        self.assertEqual(text[5], "4-6 Cheese")  # ranges scale at both ends
        self.assertEqual(res.warnings, [])

    def test_target_servings(self):
        res = scale_recipe(make(), target_servings=6)
        self.assertEqual(res.factor, F(3, 2))
        self.assertEqual(format_ingredient(res.recipe.ingredients[0]), "3 cups Flour")
        self.assertEqual(format_ingredient(res.recipe.ingredients[1]), "1 1/2 tsp Baking powder")

    def test_teaspoons_promote_to_tablespoons(self):
        r = Recipe(title="x", ingredients=[Ingredient("Salt", F(1), "tsp")])
        res = scale_recipe(r, factor=3)
        self.assertEqual(format_ingredient(res.recipe.ingredients[0]), "1 Tbsp Salt")

    def test_awkward_amounts_keep_original_unit(self):
        r = Recipe(title="x", ingredients=[Ingredient("Oil", F(5), "Tbsp")])
        res = scale_recipe(r, factor=1)
        self.assertEqual(format_ingredient(res.recipe.ingredients[0]), "5 Tbsp Oil")

    def test_original_untouched(self):
        original = make()
        scale_recipe(original, factor=2)
        self.assertEqual(original.ingredients[0].quantity, F(2))

    def test_errors(self):
        with self.assertRaises(ValueError):
            scale_recipe(make())
        with self.assertRaises(ValueError):
            scale_recipe(make(), factor=0)
        no_yield = make()
        no_yield.yield_quantity = None
        with self.assertRaises(ValueError):
            scale_recipe(no_yield, target_servings=6)


if __name__ == "__main__":
    unittest.main()


class UnitChoiceTests(unittest.TestCase):
    def _one(self, qty, unit, factor):
        r = Recipe(title="x", ingredients=[Ingredient("Thing", F(qty), unit)])
        return format_ingredient(scale_recipe(r, factor=factor).recipe.ingredients[0])

    def test_prefers_natural_units(self):
        self.assertEqual(self._one(F(7, 2), "tsp", 2), "7 tsp Thing")      # not 2 1/3 Tbsp
        self.assertEqual(self._one(F(3, 4), "cup", F(1, 2)), "6 Tbsp Thing")  # not 3/8 cup
