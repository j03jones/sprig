"""Helpers that turn editor form fields into model objects (and back), GUI-free."""
from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from typing import Iterable, List, Optional, Tuple

from .mealmaster import parse_yield
from .models import Ingredient, Recipe
from .units import canonical_unit, parse_quantity

UNIT_CHOICES = [
    "", "tsp", "Tbsp", "cup", "pint", "quart", "gallon", "oz", "lb", "g", "kg", "ml", "l",
    "can", "package", "clove", "slice", "pinch", "dash", "bunch", "stick",
    "small", "medium", "large",
]

_UNICODE_FRACTIONS = {
    "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
}


def normalize_amount(text: str) -> str:
    """'1½' -> '1 1/2', '½' -> '1/2'."""
    out = text.strip()
    for ch, plain in _UNICODE_FRACTIONS.items():
        if ch in out:
            out = out.replace(ch, f" {plain}")
    return " ".join(out.split())


def amount_for_editing(ing: Ingredient) -> str:
    """Text for the Amount cell. Exact for everyday fractions so re-saving loses nothing."""
    q = ing.quantity
    if q is None:
        return ing.raw_quantity
    if q.denominator == 1:
        return str(q.numerator)
    if q.denominator <= 16:
        whole = int(q)
        rem = q - whole
        return f"{whole} {rem}" if whole else str(rem)
    d = q.denominator
    for f in (2, 5):
        while d % f == 0:
            d //= f
    if d == 1:  # terminating decimal: write it out exactly
        return format(Decimal(q.numerator) / Decimal(q.denominator), "f").rstrip("0").rstrip(".")
    return f"{float(q):.4f}".rstrip("0").rstrip(".")


def ingredient_from_fields(amount: str, unit: str, item: str, group: str = "") -> Optional[Ingredient]:
    """Build an Ingredient from editor cells; None for a completely empty row."""
    amount, unit, item, group = amount.strip(), unit.strip(), item.strip(), group.strip()
    if not (amount or unit or item):
        return None
    amount = normalize_amount(amount)
    quantity = parse_quantity(amount)
    raw = "" if quantity is not None else amount
    canon = canonical_unit(unit)
    return Ingredient(
        item=item, quantity=quantity, unit=unit if canon is None else canon,
        group=group, raw_quantity=raw,
    )


def split_categories(text: str) -> List[str]:
    seen, out = set(), []
    for c in text.split(","):
        c = c.strip()
        if c and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)
    return out


def recipe_from_fields(
    title: str,
    categories_text: str,
    yield_text: str,
    ingredients: Iterable[Optional[Ingredient]],
    directions: str,
    recipe_id: Optional[int] = None,
    tags: Optional[List[str]] = None,
) -> Recipe:
    yq: Optional[Fraction] = None
    yu = ""
    yield_text = yield_text.strip()
    if yield_text:
        yq, yu = parse_yield(yield_text)
    return Recipe(
        id=recipe_id,
        title=title.strip(),
        ingredients=[i for i in ingredients if i is not None],
        directions=directions.strip(),
        categories=split_categories(categories_text),
        yield_quantity=yq,
        yield_unit=yu,
        yield_raw=yield_text,
        tags=list(tags or []),
    )
