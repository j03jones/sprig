"""Unit names, MealMaster unit codes, and quantity parsing/formatting."""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Optional

# MealMaster two-letter codes -> canonical display units.
MM_UNITS = {
    "ts": "tsp", "tb": "Tbsp", "c": "cup", "cu": "cup", "pt": "pint",
    "qt": "quart", "gl": "gallon", "oz": "oz", "lb": "lb", "ml": "ml",
    "dl": "dl", "l": "l", "mg": "mg", "g": "g", "kg": "kg", "cn": "can",
    "pk": "package", "ds": "dash", "pn": "pinch", "sl": "slice",
    "ea": "", "ct": "", "x": "", "ga": "gallon", "pg": "package", "cl": "clove", "sm": "small",
    "md": "medium", "lg": "large", "bn": "bunch", "bx": "box",
    "bt": "bottle", "pc": "piece", "st": "stick", "sq": "square",
    "dr": "drop", "fl": "fl oz", "tn": "tin", "ba": "bag", "jr": "jar",
    "hd": "head", "in": "inch", "ft": "foot",
}

# Free-form spellings people type -> canonical.
_ALIASES = {
    "tsp": "tsp", "tsps": "tsp", "teaspoon": "tsp", "teaspoons": "tsp", "t": "tsp",
    "tbsp": "Tbsp", "tbsps": "Tbsp", "tablespoon": "Tbsp", "tablespoons": "Tbsp",
    "tbs": "Tbsp", "tb": "Tbsp",
    "cup": "cup", "cups": "cup", "c": "cup",
    "pint": "pint", "pints": "pint", "pt": "pint",
    "quart": "quart", "quarts": "quart", "qt": "quart",
    "gallon": "gallon", "gallons": "gallon", "gal": "gallon",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "g": "g", "gram": "g", "grams": "g", "kg": "kg", "kilogram": "kg",
    "ml": "ml", "milliliter": "ml", "l": "l", "liter": "l", "litre": "l",
    "can": "can", "cans": "can", "package": "package", "packages": "package",
    "pkg": "package", "pinch": "pinch", "dash": "dash", "clove": "clove",
    "cloves": "clove", "slice": "slice", "slices": "slice",
}

# Plural forms for display when quantity > 1.
_PLURALS = {
    "pint": "pints", "quart": "quarts", "gallon": "gallons", "can": "cans",
    "package": "packages", "slice": "slices", "clove": "cloves",
    "pinch": "pinches", "dash": "dashes", "cup": "cups", "bunch": "bunches",
    "box": "boxes", "bottle": "bottles", "piece": "pieces", "stick": "sticks",
    "square": "squares", "drop": "drops", "bag": "bags", "jar": "jars",
    "head": "heads",
}

# Volume ladder in teaspoons, for smart unit promotion when scaling.
VOLUME_TSP = {"tsp": Fraction(1), "Tbsp": Fraction(3), "cup": Fraction(48)}


def canonical_unit(text: str, mealmaster: bool = False) -> Optional[str]:
    """Return the canonical unit for text, "" for blank, or None if unknown."""
    t = text.strip().rstrip(".").lower()
    if not t:
        return ""
    if mealmaster and t in MM_UNITS:
        return MM_UNITS[t]
    if t in _ALIASES:
        return _ALIASES[t]
    if t in MM_UNITS.values():
        return t
    return None


def display_unit(unit: str, quantity: Optional[Fraction]) -> str:
    if quantity is not None and quantity > 1 and unit in _PLURALS:
        return _PLURALS[unit]
    return unit


def parse_quantity(text: str) -> Optional[Fraction]:
    """Parse '2 1/4', '1/2', '1.5', '3' into a Fraction; None if not a plain amount."""
    t = text.strip()
    if not t:
        return None
    m = re.fullmatch(r"(\d+)\s+(\d+)/(\d+)", t)
    if m:
        whole, n, d = (int(x) for x in m.groups())
        return Fraction(whole) + Fraction(n, d) if d else None
    m = re.fullmatch(r"(\d+)/(\d+)", t)
    if m:
        n, d = (int(x) for x in m.groups())
        return Fraction(n, d) if d else None
    if re.fullmatch(r"\d*\.\d+|\d+", t):
        return Fraction(t)
    return None


_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d*\.\d+|\d+)"
_RANGE_RE = re.compile(rf"^({_NUM})\s*(?:-|\u2013|to)\s*({_NUM})$", re.IGNORECASE)


def parse_range(text: str):
    """'2-3', '1/2 to 1', '1 1/2-2' -> (low, high) as Fractions; None if not a rising range."""
    m = _RANGE_RE.match(text.strip())
    if not m:
        return None
    low, high = parse_quantity(m.group(1)), parse_quantity(m.group(2))
    if low is None or high is None or high <= low:
        return None
    return low, high


def format_range(low: Fraction, high: Fraction) -> str:
    return f"{format_quantity(low)}-{format_quantity(high)}"


def format_plain(q: Fraction) -> str:
    """Exact text for an amount: '3', '1/2', '1 1/2' (no rounding, unlike format_quantity)."""
    whole = int(q)
    rest = q - whole
    if rest == 0:
        return str(whole)
    return f"{whole} {rest}" if whole else str(rest)


def format_quantity(q: Optional[Fraction]) -> str:
    """Mixed fraction when close to a kitchen-friendly fraction, else a short decimal."""
    if q is None:
        return ""
    if q == 0:
        return "0"
    whole = int(q)
    frac = q - whole
    if frac == 0:
        return str(whole)
    for denom in (2, 3, 4, 8):
        nearest = Fraction(round(frac * denom), denom)
        if abs(frac - nearest) <= Fraction(1, 100) and whole + nearest > 0:
            whole += int(nearest)
            nearest -= int(nearest)
            if nearest == 0:
                return str(whole)
            return f"{whole} {nearest}" if whole else str(nearest)
    return f"{float(q):.2f}".rstrip("0").rstrip(".")
