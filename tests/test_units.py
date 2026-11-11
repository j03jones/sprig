import unittest
from fractions import Fraction as F

from recipelib.units import canonical_unit, format_quantity, parse_quantity


class QuantityTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_quantity("2 1/4"), F(9, 4))
        self.assertEqual(parse_quantity("1/2"), F(1, 2))
        self.assertEqual(parse_quantity("1.5"), F(3, 2))
        self.assertEqual(parse_quantity("3"), F(3))
        self.assertIsNone(parse_quantity("2-3"))
        self.assertIsNone(parse_quantity(""))
        self.assertIsNone(parse_quantity("1/0"))

    def test_format(self):
        self.assertEqual(format_quantity(F(9, 4)), "2 1/4")
        self.assertEqual(format_quantity(F(1, 3)), "1/3")
        self.assertEqual(format_quantity(F(3)), "3")
        self.assertEqual(format_quantity(F(33, 10)), "3.3")
        self.assertEqual(format_quantity(F(499, 100)), "5")
        self.assertEqual(format_quantity(None), "")

    def test_units(self):
        self.assertEqual(canonical_unit("ts", mealmaster=True), "tsp")
        self.assertEqual(canonical_unit("tablespoons"), "Tbsp")
        self.assertEqual(canonical_unit(""), "")
        self.assertIsNone(canonical_unit("degrees"))


if __name__ == "__main__":
    unittest.main()
