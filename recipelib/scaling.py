"""Recipe scaling by multiplier or target yield, with kitchen-friendly unit promotion."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional, Union

from .models import Ingredient, Recipe
from .units import VOLUME_TSP, format_range, parse_range

Number = Union[int, float, str, Fraction]

# (from_unit, to_unit, how many from_units make one to_unit)
_WEIGHT_STEPS = [("oz", "lb", Fraction(16)), ("g", "kg", Fraction(1000)), ("ml", "l", Fraction(1000))]


@dataclass
class ScaleResult:
    recipe: Recipe
    factor: Fraction
    warnings: List[str] = field(default_factory=list)


def _to_fraction(value: Number) -> Fraction:
    if isinstance(value, float):
        return Fraction(value).limit_denominator(1000)
    return Fraction(value)


def factor_for_servings(recipe: Recipe, target: Number) -> Fraction:
    """Multiplier that turns the recipe's current yield into the target yield."""
    if recipe.yield_quantity is None or recipe.yield_quantity <= 0:
        raise ValueError("This recipe has no numeric yield, so it can't be scaled by servings.")
    target_f = _to_fraction(target)
    if target_f <= 0:
        raise ValueError("Target yield must be greater than zero.")
    return target_f / recipe.yield_quantity


def _is_nice(q: Fraction, denominators=(2, 3, 4, 8)) -> bool:
    """True if q is whole or within 1% of a fraction with one of the given denominators."""
    frac = q - int(q)
    if frac == 0:
        return True
    return any(
        abs(frac - Fraction(round(frac * d), d)) <= Fraction(1, 100) for d in denominators
    )


# Which fractions read naturally for each volume unit ("6 Tbsp", not "3/8 cup").
_NICE_DENOMS = {"cup": (2, 3, 4), "Tbsp": (2,), "tsp": (2, 4, 8)}


def _promote_unit(quantity: Fraction, unit: str):
    """Pick the friendliest unit for an amount; keep the original if nothing reads nicely."""
    if unit in VOLUME_TSP:
        tsp = quantity * VOLUME_TSP[unit]
        for name, threshold in (("cup", Fraction(1, 4)), ("Tbsp", Fraction(1)), ("tsp", Fraction(0))):
            q = tsp / VOLUME_TSP[name]
            if q >= threshold and _is_nice(q, _NICE_DENOMS[name]):
                return q, name
        return quantity, unit
    for small, big, ratio in _WEIGHT_STEPS:
        if unit == small and quantity >= ratio and _is_nice(quantity / ratio):
            return quantity / ratio, big
    return quantity, unit


def scale_recipe(
    recipe: Recipe,
    factor: Optional[Number] = None,
    target_servings: Optional[Number] = None,
    smart_units: bool = True,
) -> ScaleResult:
    """Return a scaled copy of the recipe. Give either factor or target_servings."""
    if (factor is None) == (target_servings is None):
        raise ValueError("Give exactly one of factor or target_servings.")
    f = _to_fraction(factor) if factor is not None else factor_for_servings(recipe, target_servings)
    if f <= 0:
        raise ValueError("Scale factor must be greater than zero.")

    scaled = copy.deepcopy(recipe)
    scaled.id = None
    warnings: List[str] = []

    for ing in scaled.ingredients:
        if ing.quantity is not None:
            ing.quantity = ing.quantity * f
            if smart_units and f != 1:
                ing.quantity, ing.unit = _promote_unit(ing.quantity, ing.unit)
        elif ing.raw_quantity and parse_range(ing.raw_quantity):
            if f != 1:  # "2-3" doubled is "4-6"; the unit is left alone so both ends share it
                low, high = parse_range(ing.raw_quantity)
                ing.raw_quantity = format_range(low * f, high * f)
        elif ing.raw_quantity:
            warnings.append(f"Couldn't scale '{ing.raw_quantity} {ing.item}'; check this one by hand.")

    if scaled.yield_quantity is not None:
        scaled.yield_quantity = scaled.yield_quantity * f
    elif f != 1:
        warnings.append("This recipe has no numeric yield, so the yield was left unchanged.")

    return ScaleResult(recipe=scaled, factor=f, warnings=warnings)
