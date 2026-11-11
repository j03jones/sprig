"""Show a recipe in metric or US kitchen units.

Only like-for-like conversions are made: volume to volume (cups to millilitres) and weight to
weight (ounces to grams). A cup of flour is never turned into grams, because that depends on the
ingredient. Results are rounded to amounts you can actually measure. Ranges ("2-3 cups") and
amounts without a number are left as they are.

web/js/units.js has the JavaScript twin (convertRecipe); tests/test_convert.py checks both agree.
"""
from __future__ import annotations

import copy
from fractions import Fraction
from typing import Tuple

from .models import Recipe

SYSTEMS = ("metric", "us")

# millilitres per unit (US customary)
_ML = {
    "tsp": Fraction(4929, 1000), "Tbsp": Fraction(14787, 1000), "fl oz": Fraction(29574, 1000),
    "cup": Fraction(236588, 1000), "pint": Fraction(473176, 1000), "quart": Fraction(946353, 1000),
    "gallon": Fraction(3785412, 1000),
}
_GRAMS = {"oz": Fraction(283495, 10000), "lb": Fraction(4535924, 10000)}
_METRIC_ML = {"ml": Fraction(1), "dl": Fraction(100), "l": Fraction(1000)}
_METRIC_G = {"g": Fraction(1), "kg": Fraction(1000)}


def _round_to(value: Fraction, step: Fraction) -> Fraction:
    """Nearest multiple of step, never zero (a tiny amount stays one step)."""
    n = round(value / step)
    return (n if n else 1) * step


def _metric(value: Fraction, small: str, big: str) -> Tuple[Fraction, str]:
    if value >= 1000:
        return _round_to(value / 1000, Fraction(1, 20)), big
    step = Fraction(1, 2) if value < 10 else Fraction(5) if value < 100 else Fraction(10)
    rounded = _round_to(value, step)
    return (rounded / 1000, big) if rounded >= 1000 else (rounded, small)


def _us_volume(ml: Fraction) -> Tuple[Fraction, str]:
    if ml < _ML["Tbsp"]:
        return _round_to(ml / _ML["tsp"], Fraction(1, 4)), "tsp"
    if ml < _ML["cup"] / 4:
        return _round_to(ml / _ML["Tbsp"], Fraction(1, 2)), "Tbsp"
    if ml < _ML["gallon"]:
        return _round_to(ml / _ML["cup"], Fraction(1, 4)), "cup"
    return _round_to(ml / _ML["quart"], Fraction(1, 4)), "quart"


def _us_weight(grams: Fraction) -> Tuple[Fraction, str]:
    if grams < _GRAMS["lb"]:
        ounces = grams / _GRAMS["oz"]
        return _round_to(ounces, Fraction(1, 4) if ounces < 4 else Fraction(1, 2)), "oz"
    return _round_to(grams / _GRAMS["lb"], Fraction(1, 4)), "lb"


def convert_amount(quantity: Fraction, unit: str, system: str) -> Tuple[Fraction, str]:
    """(quantity, unit) in the given system; unchanged if the unit is not one that converts."""
    if system == "metric":
        if unit in _ML:
            return _metric(quantity * _ML[unit], "ml", "l")
        if unit in _GRAMS:
            return _metric(quantity * _GRAMS[unit], "g", "kg")
    elif system == "us":
        if unit in _METRIC_ML:
            return _us_volume(quantity * _METRIC_ML[unit])
        if unit in _METRIC_G:
            return _us_weight(quantity * _METRIC_G[unit])
    else:
        raise ValueError(f"Unknown unit system '{system}'. Use one of: {', '.join(SYSTEMS)}.")
    return quantity, unit


def convert_recipe(recipe: Recipe, system: str) -> Recipe:
    """A copy of the recipe with its measurable ingredients in the given system."""
    if system not in SYSTEMS:
        raise ValueError(f"Unknown unit system '{system}'. Use one of: {', '.join(SYSTEMS)}.")
    out = copy.deepcopy(recipe)
    for ing in out.ingredients:
        if ing.quantity is not None and ing.quantity > 0:
            ing.quantity, ing.unit = convert_amount(ing.quantity, ing.unit, system)
    return out
